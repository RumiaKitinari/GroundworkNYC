# Local Site Advisor

Open **Advisor** or go to `/?advisor=live`. Ask a question such as “Where should I look for a $35 Italian dinner spot in Queens?” Follow up with “What if I charge $45?” or “Why the first one?” The Advisor keeps the conversation’s scope and uses the dashboard’s ranking, evidence, and operating calculator. It asks for clarification when a tract name or constraint is ambiguous. The chat uses no model or hosted service.

The Advisor ships on the `ai-site-advisor` branch. The published sample runs from the files in the checkout. Live chat and rankings also need the integrated release described in the [local setup guide](OTIS_LOCAL_SETUP.md).

Ask “Where should I look in Astoria?” or “Compare Astoria and Long Island City.” The comparison shows how many tracts matched the neighborhood names in the screening dataset and summarizes only those that earned scores. The leading tract cards open property and evidence details. The chat remembers the shortlist after you ask about one tract, and a follow-up scenario stays within the named areas until you pick a new scope.

Guest-spend and trading-period what-ifs open a **preview**. Follow-up evidence questions use that preview until you **Apply scenario** or **Discard preview**. Repeated tests compare against the conversation’s applied guest spend and trading period. Apply changes only the conversation; **Undo applied scenario** restores the previous conversation settings and shortlist. A new explicit search starts from the applied settings. Dashboard filter or data-release changes still require a new chat.

Ask “What if I charge $50 per guest for the first tract?” to see that tract’s own before-and-after score and tie-aware rank within the full conversation scope. The cards show supported screening-factor changes separately from the total score change. Neighborhood scenarios retain both named groups and compare their medians and scored-tract coverage. Missing scores and changed coverage remain visible. Hypothetical rent calculations, including any paired guest spend, apply only to that calculation. These features reuse the existing ranker and make no model calls.

The chat retains dietary preferences in its scope and asks for clarification on facility requirements, geographic exclusions, walking-distance limits, or price ranges it cannot apply. When it asks which cuisine or amount to use, a short reply completes the original request. Saving a comparison location preserves the conversation, and selecting a different map location preserves completed research results. Changing the actual search or data release refreshes the relevant results.

The published sample ships as the compact public export in `demo/examples/site_advisor_sample.csv`, including in the standard Docker image. It uses nine existing synthetic screening selections across the three supported guest-spend samples.

Open **Research tools** for the Decision Lab, site brief, and two-scenario comparison. The Decision Lab compares up to nine combinations of guest spend and trading period. Its results show where candidates clearly reach the top three, where ties span the cutoff, and which supporting evidence is missing.

**Generate Site Brief** uses the current search settings and up to three saved locations, or the first three dashboard results when nothing is saved. `POST /api/site-brief` uses the existing server-side dashboard calculation.

**Generate Site Brief** renders an evidence brief without a model call. The brief shows the scenario assumptions, site-level missing evidence, property caveats, verification steps, and source names and dates where the dashboard identifies a source. **Polish wording with local AI** is optional and leaves the original evidence visible. The server rejects a polish request if the evidence has changed since the brief was generated.

The backend fixes the facts, what goes into the short brief, and their order. For optional wording, it gives `qwen2.5:3b-instruct` on loopback Ollama two equivalent wordings per location. The model returns only a few choice IDs, and the server renders the approved sentences. It cannot add numbers or claims, interpret scenarios, change filters, rank locations, or make forecasts. The evidence drawer shows the underlying measures and their basis, including unavailable fields. Synthetic property scenarios are distinct from sourced leads; an area rent benchmark is not an asking rent.

No API key, hosted inference, new Python package or fine-tuning is required. To use the optional wording polish, start Ollama with `qwen2.5:3b-instruct` installed. The original evidence brief remains visible if Ollama is unavailable, times out, or returns invalid output. The advisor also uses the template when another model is already loaded in Ollama. The advisor requests a 2,048-token context and a short 30-second keep-alive.

## Measured on Apple M4, 16 GB

Four requests, no other model loaded in Ollama, using the checked-in November 2 Italian / $35 screening export (three synthetic property scenarios):

| Check | Result |
| --- | --- |
| Cold wording request | 11.478 s wall time; 9.760 s reported model load |
| Three warm wording requests | 0.815 s, 0.809 s, 0.821 s |
| Ollama reported loaded allocation | 2,277,054,464 bytes (2.28 GB); not total system or peak memory |
| Returned only valid choices | 4/4 |

These are local wording times, not full dashboard latency or a concurrent-model benchmark. The recovered Queens sample did not meet the current dashboard's screening requirements, so the timing run used the exported scenarios. The endpoint and fallback were checked separately with test fixtures.

```bash
python demo/benchmark_site_advisor.py --offline-export reports/2026-11-02-model-results/scenarios/top_selections.csv
```

For a qualifying installed release, omit `--offline-export` and optionally set `--borough`. The benchmark leaves the model to expire under its short keep-alive.

## Compare a different scenario

From **Research tools**, open **Compare a different scenario**. Set a new spend per guest, trading period, or both. The server recomputes both shortlists with the existing dashboard engine and keeps the changes within the comparison. Results show who entered, left, or moved in the top three. The comparison requires eligible evidence in both runs and a common ranking basis.

### Upgrade evaluation

```bash
python demo/evaluate_site_advisor.py reports/2026-11-02-model-results/scenarios/top_selections.csv
PYTHONPATH=demo python -m pytest -q demo/test_site_advisor.py demo/test_entry.py demo/test_dashboard_summaries.py demo/test_financials.py demo/test_scoring.py
```

The published screening replay passed **100/100** comparisons (50 cuisines, $18→$35 and $35→$65). Membership changed in 82; the ordered top three changed in 85 including membership changes. The replay checks reporting against saved synthetic property selections. It does not regenerate scores, test trading-period changes on a full live dataset, or validate outcomes. The HTTP tests check parameter changes, insufficient evidence, and that scenario comparisons never call the language model.

Next evaluation: run price and trading-period comparisons with a qualifying integrated release and verify the results against direct dashboard requests. Use that evidence to decide whether individual scenario controls or the short brief need further refinement before adding more AI complexity.


## Try the tab without installing data

In the existing dashboard, open **Site Advisor** and switch **Data source** to **Published sample**. To jump straight to that state, open `/?advisor=sample` (or the redirect at `/site-advisor-preview`). The app keeps the standard dashboard navigation and uses the published Italian screening sample only for this tab. Generate a brief or replay the saved $18 or $65 scenario against the $35 baseline. Properties are synthetic, and the preview never recomputes rankings. The normal tab uses the current integrated release and supports live spend and trading-period changes.
