#!/usr/bin/env python3
"""
estrazione.py - Motore di estrazione robusto per modelli con thinking.

Separa e preserva:
    - thinking      : il ragionamento del modello (per log e analisi dei disaccordi)
    - content       : la risposta finale ripulita dal reasoning
    - json          : l'oggetto strutturato, se presente e valido
    - decisione     : il campo decisione_finale, estratto in modo tollerante

Gestisce i tre formati dei modelli del SET 7:
    - qwen3, gemma 4  -> tag <think>...</think>
    - gpt-oss         -> formato Harmony, canali <|channel|>analysis|final<|message|>

Strategia a robustezza decrescente:
    1. se la risposta arriva gia separata da Ollama (campi 'thinking' e 'content'
       distinti via /api/chat con think=true), si usa quella separazione nativa;
    2. altrimenti si ripuliscono i blocchi di reasoning dal testo grezzo;
    3. l'estrazione del JSON e tollerante: prende l'ULTIMO oggetto valido, e in
       caso di JSON malformato (tipico di gpt-oss in Harmony) ripiega su una
       ricerca mirata dell'ultima decisione_finale.

Nota: il JSON rigido a livello di API (format=json) NON e raccomandato per
gpt-oss, che con Harmony tende a produrre JSON sporco. Si chiede il JSON nel
prompt e lo si estrae qui in modo tollerante.
"""

import re
import json

# Insieme chiuso delle decisioni ammesse.
DECISIONI_VALIDE = {"PROCEDI", "CAUTELA", "VETO", "CHIEDI_INFO"}

# Marcatori di reasoning per i due schemi (think-tag e Harmony).
_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)
_HARMONY_ANALYSIS = re.compile(
    r"<\|channel\|>\s*analysis\s*<\|message\|>.*?(?=<\|(?:end|start|channel|return)\|>|$)",
    re.IGNORECASE | re.DOTALL,
)
_HARMONY_TAGS = re.compile(r"<\|[^|>]*\|>", re.IGNORECASE)


def _rimuovi_reasoning(testo):
    """Rimuove i blocchi di ragionamento da un testo grezzo, restituendo
    (thinking_estratto, testo_senza_reasoning)."""
    if not testo:
        return "", ""
    thinking_parti = []

    # 1) blocchi <think>...</think>: tutto cio che sta prima di </think> e reasoning
    if _THINK_CLOSE.search(testo):
        # puo esserci o no il tag di apertura; si taglia tutto fino all'ultimo </think>
        idx = list(_THINK_CLOSE.finditer(testo))[-1].end()
        prima = testo[:idx]
        # estrae il contenuto del think per preservarlo
        m = re.search(r"<think>(.*?)</think>", prima, re.IGNORECASE | re.DOTALL)
        thinking_parti.append(m.group(1).strip() if m else _THINK_OPEN.sub("", _THINK_CLOSE.sub("", prima)).strip())
        testo = testo[idx:]

    # 2) canali Harmony 'analysis' (reasoning di gpt-oss)
    for m in _HARMONY_ANALYSIS.finditer(testo):
        thinking_parti.append(m.group(0))
    testo = _HARMONY_ANALYSIS.sub("", testo)

    # 3) rimuove eventuali tag Harmony residui (<|channel|>, <|message|>, <|final|>, ecc.)
    #    isolando il contenuto del canale 'final' se presente
    mfin = re.search(r"<\|channel\|>\s*final\s*<\|message\|>(.*)$", testo, re.IGNORECASE | re.DOTALL)
    if mfin:
        testo = mfin.group(1)
    testo = _HARMONY_TAGS.sub("", testo)

    thinking = "\n".join(t for t in thinking_parti if t).strip()
    return thinking, testo.strip()


def _estrai_ultimo_json(testo):
    """Cerca l'ULTIMO oggetto JSON valido nel testo. Ritorna dict o None.
    Scansiona da destra: utile quando il reasoning contiene frammenti simil-JSON
    che non devono essere agganciati al posto della risposta finale."""
    if not testo:
        return None
    # rimuove eventuali fence markdown
    pulito = re.sub(r"```(?:json)?", "", testo)
    # trova tutte le posizioni di '{' e prova a chiudere un oggetto valido,
    # privilegiando l'ultimo oggetto ben formato
    candidati = []
    for start in (i for i, c in enumerate(pulito) if c == "{"):
        profondita = 0
        for end in range(start, len(pulito)):
            if pulito[end] == "{":
                profondita += 1
            elif pulito[end] == "}":
                profondita -= 1
                if profondita == 0:
                    frammento = pulito[start:end + 1]
                    try:
                        candidati.append(json.loads(frammento))
                    except Exception:
                        pass
                    break
    return candidati[-1] if candidati else None


def _estrai_decisione_fallback(testo):
    """Ripiego: se il JSON e malformato, pesca l'ULTIMA decisione_finale via regex.
    L'ultima occorrenza e quella conclusiva, non un valore 'considerato' nel mezzo."""
    if not testo:
        return None
    occorrenze = re.findall(r'"?decisione_finale"?\s*[:=]\s*"?([A-Z_]+)"?', testo, re.IGNORECASE)
    for val in reversed(occorrenze):
        v = val.strip().upper()
        if v in DECISIONI_VALIDE:
            return v
    # ultimo tentativo: una decisione valida citata da sola, l'ultima nel testo
    parole = re.findall(r"\b(PROCEDI|CAUTELA|VETO|CHIEDI_INFO)\b", testo, re.IGNORECASE)
    if parole:
        return parole[-1].strip().upper()
    return None


def estrai(risposta_ollama):
    """Estrae thinking, content, json e decisione da una risposta Ollama.

    Accetta:
      - dict in stile /api/chat con eventuali campi 'thinking' e 'content'
        (separazione nativa di Ollama con think=true), oppure
      - dict con 'response'/'raw' grezzo, oppure
      - stringa grezza.

    Ritorna un dict:
      {"thinking": str, "content": str, "json": dict|None, "decisione": str|None}
    """
    thinking_nativo = ""
    grezzo = ""

    if isinstance(risposta_ollama, dict):
        # separazione nativa Ollama (preferita)
        msg = risposta_ollama.get("message") or {}
        thinking_nativo = (msg.get("thinking") or risposta_ollama.get("thinking") or "").strip()
        grezzo = (msg.get("content") or risposta_ollama.get("content")
                  or risposta_ollama.get("response") or risposta_ollama.get("raw") or "")
    else:
        grezzo = str(risposta_ollama or "")

    # se Ollama ha gia separato il thinking, il content e gia pulito dal reasoning;
    # puo comunque contenere residui di tag, quindi si passa comunque dal ripulitore,
    # che e idempotente (se non trova reasoning, lascia il testo invariato).
    thinking_estratto, content = _rimuovi_reasoning(grezzo)

    thinking = thinking_nativo or thinking_estratto

    # estrazione JSON sul content ripulito
    obj = _estrai_ultimo_json(content)
    decisione = None
    if obj and isinstance(obj, dict):
        val = str(obj.get("decisione_finale", "")).strip().upper()
        if val in DECISIONI_VALIDE:
            decisione = val
    if decisione is None:
        # ripiego tollerante su content, poi su tutto il grezzo
        decisione = _estrai_decisione_fallback(content) or _estrai_decisione_fallback(grezzo)

    return {
        "thinking": thinking,
        "content": content,
        "json": obj,
        "decisione": decisione,
    }


if __name__ == "__main__":
    # autotest con i tre formati piu un caso sporco
    casi = {
        "qwen3/gemma think-tag": (
            "<think>La situazione ha un backup incompleto. Potrei dire PROCEDI ma "
            "il rischio e alto, meglio fermarsi.</think>\n"
            '{"valutazione_iniziale": "rischio dati", "decisione_finale": "VETO"}'
        ),
        "gpt-oss harmony": (
            "<|channel|>analysis<|message|>Considero PROCEDI ma manca lo staging, "
            "quindi CHIEDI_INFO.<|end|><|start|>assistant<|channel|>final<|message|>"
            '{"decisione_finale": "CHIEDI_INFO"}'
        ),
        "separazione nativa ollama": {
            "message": {
                "thinking": "Backup ok, staging sincronizzato, patch minore.",
                "content": '{"decisione_finale": "PROCEDI"}',
            }
        },
        "json sporco (gpt-oss)": (
            "<|channel|>final<|message|>Ecco la valutazione: "
            '{"decisione_finale": "CAUTELA", "piano": [oops non valido}'
        ),
        "frammento ingannevole nel think": (
            "<think>Una prima ipotesi sarebbe decisione_finale: PROCEDI, ma "
            "riconsiderando i dati e VETO.</think>\n"
            '{"decisione_finale": "VETO"}'
        ),
    }
    for nome, r in casi.items():
        out = estrai(r)
        print(f"[{nome}]")
        print(f"  decisione: {out['decisione']}")
        print(f"  thinking preservato: {bool(out['thinking'])} ({len(out['thinking'])} char)")
        print(f"  json valido: {out['json'] is not None}")
        print()
