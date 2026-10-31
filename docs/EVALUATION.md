# Evaluation

ORYN can score retrieval and answer quality on **your own** question set. There are no built-in benchmark numbers; the dashboard shows
nothing until you run an evaluation.

## Dataset format
```json
{
  "name": "Refund policy v1",
  "samples": [
    {
      "question": "What is the refund window?",
      "ground_truth": "30 days from purchase",
      "relevant_documents": ["policy.pdf"]
    }
  ]
}
```
`ground_truth` and `relevant_documents` (filenames as shown in the Knowledge Base) are optional per sample. At most 50 samples per run.

## Metrics
| Metric | Needs | Definition |
|---|---|---|
| context_precision | relevant_documents | relevant context chunks / context chunks supplied to the model (0 when none were supplied) |
| context_recall | relevant_documents | labelled relevant documents present in the context / labelled relevant documents |
| hit_rate | relevant_documents | 1 if at least one relevant document was retrieved, else 0 |
| faithfulness | `judge` enabled | LLM judge: supported claims / total claims in the answer, judged against the context |
| answer_relevance | `judge` enabled | LLM judge score 1-5 for how directly the answer addresses the question, rescaled to 0-1 |
| answer_correctness | `judge` + ground_truth | LLM judge score 1-5 for agreement with ground_truth, rescaled to 0-1 |
| retrieval_ms, rerank_ms, generation_ms, total_ms | always | measured latency |

Retrieval metrics are **document-level**, not chunk-level. A metric that cannot be computed for a sample is stored as null and excluded from the
mean; every aggregate reports `n`, the number of samples that contributed. Nothing is imputed. LLM-judged metrics are skipped for abstained answers and are opt-in because they make extra
OpenAI calls (cost) and are estimates that can be biased. Small datasets give noisy scores; treat them as a regression signal, not a guarantee.

## Running
- UI: **Analytics -> Evaluation runs -> New evaluation** (workspace owner/admin).
- CLI: `python -m app.cli evaluate --workspace <workspace id> --dataset dataset.json [--judge]`.
- API: `POST /api/v1/workspaces/{id}/evaluations` then poll `GET .../evaluations/{run id}`.

Runs execute in a background thread of the API process; a run left "running" for over an hour is marked failed. These runs call the real providers, so
they cost money and need valid keys. The evaluation code was tested with fake providers only.
