"""Somministrazione della suite di valutazione modelli (Fase 1) - versione 2.

A differenza di batch_compare.py (che legge email reali via IMAP e richiede il
container), questo motore e autonomo: legge casi sintetici da un file YAML, li
invia a ciascun modello via Ollama, e raccoglie le risposte affiancate per la
valutazione. Non richiede Docker ne IMAP: gira nativo con Python + requests,
parlando solo all'endpoint Ollama.

Novita della versione 2 (per il SET 3):
- EVAL_REPS: ogni caso puo essere ripetuto N volte per modello, per misurare la
  riproducibilita del verdetto (test di stabilita).
- Salvataggio incrementale: dopo OGNI risposta viene aggiunta una riga a un file
  JSONL grezzo; un'interruzione a meta giro non perde piu i risultati gia
  raccolti. CSV e file leggibile restano scritti a fine giro come prima.
- EVAL_TEMPERATURE: se impostata, sovrascrive la temperatura di fabbrica del
  modello (per il confronto stabilita a temperatura bassa).
- EVAL_THINK: controllo del campo "think" della richiesta (default: false, come
  nei giri precedenti). Per i modelli con reasoning effort regolabile accetta
  anche low/medium/high. La semantica esatta varia per modello: verificare sul
  primo caso che la risposta resti JSON valido.

Uso:
    python batch_eval.py                          # tutti i casi, modelli da config
    python batch_eval.py --famiglia veto          # solo una famiglia
    python batch_eval.py --casi S3-A1,S3-A2       # casi specifici

Ambiente:
    OLLAMA_URL          endpoint Ollama (default http://localhost:11434)
    EVAL_MODELS_FILE    lista modelli, uno per riga (default eval_models.txt)
    EVAL_CASES_FILE     file YAML dei casi (default eval_cases.yaml)
    EVAL_OUTPUT_DIR     cartella output (default directory corrente)
    EVAL_NUM_CTX        finestra di contesto (default 8192)
    EVAL_TIMEOUT        timeout per richiesta in secondi (default 600)
    EVAL_REPS           ripetizioni per caso (default 1)
    EVAL_TEMPERATURE    temperatura di campionamento (default: di fabbrica)
    EVAL_THINK          false | true | low | medium | high (default false)
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime

import requests
import yaml

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("suite-eval")


def get_env(name, default=None):
    return os.environ.get(name, default)


def load_models(path):
    """Carica la lista modelli dal file di config (ignora vuote e commenti #)."""
    models = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                models.append(stripped)
    if not models:
        raise RuntimeError(f"Nessun modello attivo in {path}")
    return models


def load_cases(path):
    """Carica system_prompts e casi dal file YAML."""
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data["system_prompts"], data["cases"]


def parse_think(value):
    """Interpreta EVAL_THINK: booleano o livello di reasoning effort.

    Restituisce il valore da inserire nel campo "think" della richiesta API.
    """
    normalized = str(value).strip().lower()
    if normalized in ("false", "0", "no", ""):
        return False
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("low", "medium", "high"):
        return normalized
    raise RuntimeError(f"EVAL_THINK non riconosciuto: {value}")


def query_model(ollama_url, model, system_prompt, user_input, num_ctx, timeout,
                temperature=None, think=False):
    """Invia un singolo caso a un modello e restituisce la risposta grezza.

    Richiede output JSON per coerenza con il sistema di produzione e per poter
    estrarre il verdetto. In caso di errore restituisce un marcatore di errore,
    senza interrompere il giro: un modello che fallisce un caso non deve fermare
    l'intera suite.
    """
    options = {"num_ctx": num_ctx}
    if temperature is not None:
        options["temperature"] = temperature
    try:
        response = requests.post(
            f"{ollama_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                "stream": False,
                "format": "json",
                "options": options,
                "think": think,
                "keep_alive": "30m",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        return {"ok": True, "raw": content}
    except (requests.RequestException, KeyError, ValueError) as error:
        return {"ok": False, "raw": f"[ERRORE: {error}]"}


def extract_verdict(raw):
    """Estrae un verdetto sintetico dalla risposta JSON, se presente.

    Cerca le chiavi di verdetto usate dai vari system prompt (decisione, classe,
    esito). Se la risposta non e JSON parsabile o non contiene un verdetto noto,
    restituisce stringa vuota: la risposta resta comunque salvata per intero
    nell'output leggibile.
    """
    cleaned = str(raw).strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1]
            if cleaned.lstrip().lower().startswith("json"):
                cleaned = cleaned.lstrip()[4:]
    a, b = cleaned.find("{"), cleaned.rfind("}")
    if a != -1 and b != -1 and b > a:
        cleaned = cleaned[a:b + 1]
    try:
        parsed = json.loads(cleaned)
    except (ValueError, TypeError):
        return ""
    for key in ("decisione", "classe", "esito", "categoria"):
        if key in parsed:
            return str(parsed[key]).strip()
    return ""


def summarize_reps(rep_list):
    """Riassume i verdetti delle ripetizioni di un caso in una stringa compatta.

    Con una sola ripetizione restituisce il verdetto cosi com'e. Con piu
    ripetizioni produce un conteggio per verdetto, ad esempio "CAUTELA 3/3"
    oppure "CAUTELA 2/3; PROCEDI 1/3", utile per leggere la stabilita a colpo
    d'occhio nel CSV.
    """
    verdicts = [r["verdict"] or "(n/d)" for r in rep_list]
    if len(verdicts) == 1:
        return verdicts[0]
    counts = {}
    for v in verdicts:
        counts[v] = counts.get(v, 0) + 1
    total = len(verdicts)
    parts = sorted(counts.items(), key=lambda kv: -kv[1])
    return "; ".join(f"{v} {n}/{total}" for v, n in parts)


def main():
    parser = argparse.ArgumentParser(description="Suite di valutazione modelli.")
    parser.add_argument("--famiglia", help="esegui solo una famiglia")
    parser.add_argument("--casi", help="esegui solo casi specifici (id separati da virgola)")
    args = parser.parse_args()

    ollama_url = get_env("OLLAMA_URL", "http://localhost:11434")
    models_file = get_env("EVAL_MODELS_FILE", "eval_models.txt")
    cases_file = get_env("EVAL_CASES_FILE", "eval_cases.yaml")
    output_dir = get_env("EVAL_OUTPUT_DIR", ".")
    num_ctx = int(get_env("EVAL_NUM_CTX", "8192"))
    timeout = int(get_env("EVAL_TIMEOUT", "600"))
    reps = int(get_env("EVAL_REPS", "1"))
    temperature_env = get_env("EVAL_TEMPERATURE")
    temperature = float(temperature_env) if temperature_env else None
    think = parse_think(get_env("EVAL_THINK", "false"))

    models = load_models(models_file)
    system_prompts, cases = load_cases(cases_file)

    # Filtri opzionali.
    if args.famiglia:
        cases = [c for c in cases if c["famiglia"] == args.famiglia]
    if args.casi:
        wanted = {x.strip() for x in args.casi.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        raise RuntimeError("Nessun caso selezionato dai filtri indicati.")

    logger.info("Modelli: %s", ", ".join(models))
    logger.info("Casi: %d  |  Famiglie: %s  |  Ripetizioni: %d",
                len(cases), ", ".join(sorted({c["famiglia"] for c in cases})), reps)
    if temperature is not None:
        logger.info("Temperatura forzata: %s", temperature)
    if think is not False:
        logger.info("Think: %s", think)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # File JSONL grezzo, aperto in append e scritto DOPO OGNI risposta: e la
    # rete di sicurezza contro le interruzioni. Ogni riga e autosufficiente
    # (modello, caso, ripetizione, verdetto, risposta grezza, esito chiamata).
    jsonl_path = os.path.join(output_dir, f"eval_grezzo_{timestamp}.jsonl")
    logger.info("Salvataggio incrementale su: %s", jsonl_path)

    # Struttura risultati: results[case_id][model] = lista di ripetizioni,
    # ciascuna {"raw":..., "verdict":...}.
    results = {c["id"]: {} for c in cases}

    # Ciclo per modello (esterno) cosi ogni modello e caricato in memoria una
    # volta sola e processa tutti i casi prima di passare al successivo: con
    # OLLAMA_MAX_LOADED_MODELS=1 evita ricariche continue del modello.
    for model in models:
        logger.info("=== Modello: %s ===", model)
        started = time.time()
        for index, case in enumerate(cases, start=1):
            sp = system_prompts[case["system_prompt"]]
            rep_list = []
            for rep in range(1, reps + 1):
                outcome = query_model(
                    ollama_url, model, sp, case["input"], num_ctx, timeout,
                    temperature=temperature, think=think,
                )
                verdict = extract_verdict(outcome["raw"]) if outcome["ok"] else "ERRORE"
                rep_list.append({"raw": outcome["raw"], "verdict": verdict})

                # Scrittura incrementale immediata (append + flush).
                with open(jsonl_path, "a", encoding="utf-8") as jl:
                    jl.write(json.dumps({
                        "modello": model,
                        "caso": case["id"],
                        "famiglia": case["famiglia"],
                        "rep": rep,
                        "ok": outcome["ok"],
                        "verdetto": verdict,
                        "raw": outcome["raw"],
                    }, ensure_ascii=False) + "\n")

                rep_label = f" rep {rep}/{reps}" if reps > 1 else ""
                logger.info(
                    "[%s] [%d/%d] caso %s (%s)%s -> verdetto: %s",
                    model, index, len(cases), case["id"], case["famiglia"],
                    rep_label, verdict or "(non estratto)",
                )
            results[case["id"]][model] = rep_list
        elapsed = time.time() - started
        logger.info("Modello %s completato in %.0fs (%.1fs/caso, %d rip.).",
                    model, elapsed, elapsed / (len(cases) * reps), reps)

    # Output 1: CSV con verdetti affiancati (colpo d'occhio). Con ripetizioni
    # attive, ogni cella riassume il conteggio dei verdetti (vedi summarize_reps).
    csv_path = os.path.join(output_dir, f"eval_verdetti_{timestamp}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "famiglia", "verdetto_atteso"] + models)
        for case in cases:
            row = [case["id"], case["famiglia"], case.get("verdetto_atteso", "")]
            for model in models:
                row.append(summarize_reps(results[case["id"]][model]))
            writer.writerow(row)
    logger.info("CSV verdetti scritto in: %s", csv_path)

    # Output 2: file leggibile con le risposte complete per esame umano. Con
    # ripetizioni attive riporta tutte le risposte, etichettate per ripetizione.
    txt_path = os.path.join(output_dir, f"eval_risposte_{timestamp}.txt")
    with open(txt_path, "w", encoding="utf-8") as handle:
        for case in cases:
            handle.write("=" * 78 + "\n")
            handle.write(f"CASO {case['id']}  [{case['famiglia']}]\n")
            handle.write("-" * 78 + "\n")
            handle.write("INPUT:\n")
            handle.write(case["input"].rstrip() + "\n\n")
            handle.write(f"VERDETTO ATTESO: {case.get('verdetto_atteso', '(n/d)')}\n")
            if case.get("criteri_contenuto"):
                handle.write("CRITERI DI CONTENUTO ATTESI:\n")
                for crit in case["criteri_contenuto"]:
                    handle.write(f"  - {crit}\n")
            if case.get("criteri_negativi"):
                handle.write("DA NON FARE:\n")
                for crit in case["criteri_negativi"]:
                    handle.write(f"  - {crit}\n")
            handle.write("\n" + "-" * 78 + "\n")
            handle.write("RISPOSTE DEI MODELLI:\n\n")
            for model in models:
                rep_list = results[case["id"]][model]
                for rep_index, entry in enumerate(rep_list, start=1):
                    rep_label = f" [rep {rep_index}/{len(rep_list)}]" if len(rep_list) > 1 else ""
                    handle.write(f"### {model}{rep_label}  (verdetto estratto: "
                                 f"{entry['verdict'] or 'n/d'})\n")
                    raw = entry["raw"]
                    # Se la risposta e JSON, la riformatto leggibile; altrimenti grezza.
                    try:
                        parsed = json.loads(raw)
                        handle.write(json.dumps(parsed, ensure_ascii=False, indent=2))
                    except (ValueError, TypeError):
                        handle.write(raw)
                    handle.write("\n\n")
            handle.write("\n")
    logger.info("Risposte leggibili scritte in: %s", txt_path)

    # Riepilogo verdetti vs atteso (solo dove il verdetto e estraibile e atteso noto).
    logger.info("--- Riepilogo verdetti (dove confrontabile) ---")
    for case in cases:
        atteso = str(case.get("verdetto_atteso", "")).strip()
        if not atteso:
            continue
        verdetti = {m: summarize_reps(results[case["id"]][m]) for m in models}
        logger.info("Caso %s | atteso ~ '%s' | %s",
                    case["id"], atteso,
                    "  ".join(f"{m}={v or '-'}" for m, v in verdetti.items()))


if __name__ == "__main__":
    main()
