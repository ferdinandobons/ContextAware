# ContextAware

> **Vendor-agnostic Context Management Framework for Coding Agents**

ContextAware risolve il problema strutturale del *context management* nei coding agents basati su LLM. Permette di gestire repository complessi trattando il contesto non come una semplice stringa di testo, ma come un database strutturato e interrogabile.

Il framework è progettato per ridurre drasticamente il consumo di token e migliorare la coerenza delle risposte degli agenti, fornendo solo il contesto strettamente necessario per ogni specifico task.

---

## 🚀 Filosofia e Vantaggi

*   **Context as a Database**: Il contesto è una struttura indicizzata, versionata e interrogabile.
*   **Token Efficiency**: Ogni token inviato all'LLM deve essere giustificato. Il sistema filtra il rumore.
*   **Layered Context**: Distingue tra contesto globale, di progetto, semantico e volatile.
*   **Vendor-agnostic**: Funziona con qualsiasi LLM (GPT, Claude, Gemini) e qualsiasi framework di agenti.

---

## 🏗 Architettura e Concetti

Il sistema suddivide il contesto in **Layer** per garantire che l'agente riceva sempre il livello di dettaglio corretto:

1.  **Global Context**: Convenzioni, stile e framework (Statico).
2.  **Project Context**: Struttura repo, moduli principali (Aggiornato via analisi statica).
3.  **Semantic Context**: Simboli, funzioni, classi e relazioni (Graph-based).
4.  **Task Context**: Obiettivi e vincoli del task corrente (Volatile).

### Componenti del Sistema

*   **Context Store**: Database JSON locale che persiste la conoscenza del progetto.
*   **Project Analyzer**: Motore di analisi statica (AST) che indicizza il codice.
*   **Context Router**: Seleziona i "pezzi" di contesto rilevanti basandosi sulla query.
*   **Prompt Compiler**: Assembla i pezzi selezionati in un formato XML/Markdown ottimizzato per l'LLM.

---

## 📦 Installazione

Requisiti: Python 3.8+

```bash
# Installazione in modalità editabile (sviluppo)
pip install -e .
```

---

## 🛠 Utilizzo

ContextAware espone una CLI per gestire il ciclo di vita del contesto.

### 1. Inizializzazione
Prepara il progetto target creando lo store locale.

```bash
python3 -m context_aware.cli.main init
```

### 2. Indicizzazione
Analizza il codice sorgente per popolare il Context Store.

```bash
# Indicizza l'intera cartella corrente
python3 -m context_aware.cli.main index .
```

### 3. Querying (Human Usage)
Per testare cosa "vede" il sistema per un dato argomento.

```bash
python3 -m context_aware.cli.main query "autenticazione utente"
```

---

## 🤖 Integrazione con Coding Agents

Questa è la funzionalità core di ContextAware. Un agente autonomo non dovrebbe leggere ciecamente i file, ma usare ContextAware per orientarsi.

### Workflow Consigliato

1.  **Task Reception**: L'agente riceve un task (es. "Refactor login function").
2.  **Context Discovery**: L'agente interroga il sistema.
    *   Command: `context_aware query "login function refactor"`
3.  **Context Injection**: Il sistema restituisce un blocco XML strutturato con:
    *   Definizioni delle funzioni pertinenti.
    *   Percorsi dei file coinvolti.
    *   Docstring e metadati.
4.  **Targeted Action**: L'agente, ora consapevole di *dove* si trova il codice, apre solo i file necessari e procede con sicurezza.

**Vantaggi per l'Agente:**
*   Elimina il fenomeno "Lost in the Middle".
*   Riduce i costi per token di input.
*   Aumenta la precisione nelle modifiche multi-file.
