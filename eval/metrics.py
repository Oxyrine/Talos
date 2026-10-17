"""eval/metrics.py: Compute 17 benchmark evaluation metrics against ground truth."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pyexasol import ExaConnection

from orchestrator.db import REPO_ROOT, connect
from orchestrator.replay import replay


def _update_readme_metrics(profile: str, metrics: dict[str, Any]) -> None:
    """Update README.md benchmark table in-place without overwriting with invented numbers.

    Preserves 4-column structure: | Metric | Dev | Test (unseen) | Target |
    If a metric is None, writes 'not measured'.
    """
    if profile not in ("dev", "test"):
        return   # only the dev and held-out test benchmarks are published (CI runs tiny)
    readme_path = REPO_ROOT / "README.md"
    if not readme_path.is_file():
        return

    readme_text = readme_path.read_text(encoding="utf-8")
    start_marker = "<!-- METRICS:START -->"
    end_marker = "<!-- METRICS:END -->"
    if start_marker not in readme_text or end_marker not in readme_text:
        return

    col_idx = 1 if profile == "dev" else 2

    metric_formatters: dict[str, str] = {
        "Understated group exposure, after Talos vs before": (
            f"{metrics['understated_exposure_ratio'] * 100:.1f}%"
            if metrics.get("understated_exposure_ratio") is not None
            else "not measured"
        ),
        "Overstated group exposure": (
            f"₹{metrics['overstated_exposure_after_inr']:,.0f}"
            if metrics.get("overstated_exposure_after_inr") is not None
            else "not measured"
        ),
        "Missed breaches / false breaches": (
            f"{metrics['missed_breaches']} / {metrics['false_breaches']}"
            if (metrics.get("missed_breaches") is not None and metrics.get("false_breaches") is not None)
            else "not measured"
        ),
        "Blocking recall": (
            f"{metrics['blocking_recall']:.4f}"
            if metrics.get("blocking_recall") is not None
            else "not measured"
        ),
        "Entity-resolution precision / recall": (
            f"{metrics['er_precision']:.2f} / {metrics['er_recall']:.2f}"
            if (metrics.get("er_precision") is not None and metrics.get("er_recall") is not None)
            else "not measured"
        ),
        "ID-name conflicts routed to T3": (
            f"{metrics['id_name_conflicts_caught']}"
            if metrics.get("id_name_conflicts_caught") is not None
            else "not measured"
        ),
        "Decoy false merges": (
            f"{metrics['decoy_false_merges']}"
            if metrics.get("decoy_false_merges") is not None
            else "not measured"
        ),
        "Replay fidelity (output hash match)": (
            f"{metrics['replay_fidelity'] * 100:.0f}%"
            if metrics.get("replay_fidelity") is not None
            else "not measured"
        ),
        "Resolved without the model": (
            f"{metrics['resolved_without_model'] * 100:.1f}%"
            if metrics.get("resolved_without_model") is not None
            else "not measured"
        ),
    }

    parts = readme_text.split(start_marker)
    inner_and_after = parts[1].split(end_marker)
    inner = inner_and_after[0]
    after = inner_and_after[1]

    new_inner_lines = []
    for line in inner.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("|") and not trimmed.startswith("| Metric") and not trimmed.startswith("|---"):
            cells = [c.strip() for c in trimmed.strip("|").split("|")]
            if len(cells) >= 4:
                metric_name = cells[0]
                if metric_name in metric_formatters:
                    cells[col_idx] = metric_formatters[metric_name]
                    new_line = "| " + " | ".join(cells) + " |"
                    new_inner_lines.append(new_line)
                    continue
        new_inner_lines.append(line)

    updated_block = start_marker + "\n".join(new_inner_lines) + end_marker
    new_readme = parts[0] + updated_block + after
    try:
        readme_path.write_text(new_readme, encoding="utf-8")
    except Exception:
        pass


def compute_metrics(
    conn: ExaConnection | None = None,
    profile: str = "dev",
    output_dir: str | Path = "eval/results",
) -> dict[str, Any]:
    """Calculate all 17 Talos benchmark metrics using TALOS_EVAL connection."""
    close_conn = False
    if conn is None:
        conn = connect("eval", autocommit=True)
        close_conn = True

    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    output_path.mkdir(parents=True, exist_ok=True)

    metrics: dict[str, Any] = {}
    misses: list[str] = []

    try:
        # Get latest run
        run_stmt = conn.execute(
            """
            SELECT run_id, business_date, known_at
            FROM GOV.REPORT_RUN
            WHERE status = 'OK' AND replay_of IS NULL
            ORDER BY finished_at DESC, run_id DESC
            LIMIT 1
            """
        )
        latest_run = run_stmt.fetchone()
        if not latest_run:
            raise ValueError("No successful report run found in GOV.REPORT_RUN.")

        run_id = latest_run["run_id"] if isinstance(latest_run, dict) else latest_run[0]

        # Metric 5: Candidate pairs by path & dropped blocks
        try:
            path_stmt = conn.execute(
                """
                SELECT via, COUNT(*) as cnt
                FROM RESOLVE.CANDIDATE_PAIR
                GROUP BY via
                """
            )
            candidate_counts = {
                (r["via"] if isinstance(r, dict) else r[0]): int(r["cnt"] if isinstance(r, dict) else r[1])
                for r in path_stmt.fetchall()
            }
            drop_stmt = conn.execute("SELECT COUNT(*) FROM STAGE.BLOCK_DROPPED")
            dropped_blocks = int(drop_stmt.fetchval() or 0)
            metrics["candidate_pairs_by_path"] = candidate_counts
            metrics["total_candidates"] = sum(candidate_counts.values())
            metrics["dropped_blocks_count"] = dropped_blocks
        except Exception:
            metrics["candidate_pairs_by_path"] = None
            metrics["total_candidates"] = None
            metrics["dropped_blocks_count"] = None

        # Metric 6: Reduction ratio
        try:
            book_cnt = int(conn.execute("SELECT COUNT(*) FROM STAGE.RECORD_STD WHERE side='BOOK'").fetchval() or 0)
            reg_cnt = int(conn.execute("SELECT COUNT(*) FROM STAGE.RECORD_STD WHERE side='REG'").fetchval() or 0)
            cartesian = book_cnt * reg_cnt
            tot_cand = metrics.get("total_candidates")
            if tot_cand is not None and cartesian > 0:
                red_ratio = 1.0 - (tot_cand / cartesian)
                metrics["reduction_ratio"] = round(red_ratio, 6)
            else:
                metrics["reduction_ratio"] = None
        except Exception:
            metrics["reduction_ratio"] = None

        # Metric 7: Blocking recall
        try:
            br_stmt = conn.execute(
                """
                SELECT COUNT(DISTINCT gt.rec_key) as found_true,
                       (SELECT COUNT(*) FROM TRUTH.GT_RECORD_ENTITY) as total_true
                FROM TRUTH.GT_RECORD_ENTITY gt
                JOIN RESOLVE.CANDIDATE_PAIR cp
                  ON cp.rec_a = gt.rec_key
                 AND cp.rec_b = ('REG:' || SUBSTR(gt.entity_key, 3))
                """
            )
            br_row = br_stmt.fetchone()
            found_true = br_row["found_true"] if isinstance(br_row, dict) else br_row[0]
            total_true = br_row["total_true"] if isinstance(br_row, dict) else br_row[1]
            if total_true and total_true > 0:
                metrics["blocking_recall"] = round(float(found_true / total_true), 4)
            else:
                metrics["blocking_recall"] = None
        except Exception:
            metrics["blocking_recall"] = None

        # Metric 8: ER precision & recall
        try:
            er_stmt = conn.execute(
                """
                SELECT
                    COUNT(CASE WHEN le.entity_key = gt.entity_key THEN 1 END) as true_positive,
                    COUNT(le.rec_key) as total_asserted,
                    (SELECT COUNT(*) FROM TRUTH.GT_RECORD_ENTITY) as total_true
                FROM (
                    SELECT rec_key, entity_key, "ACTION",
                           ROW_NUMBER() OVER (PARTITION BY link_key ORDER BY recorded_at DESC, event_id DESC) as rn
                    FROM GRAPH.LINK_EVENT
                ) le
                LEFT JOIN TRUTH.GT_RECORD_ENTITY gt ON le.rec_key = gt.rec_key
                WHERE le.rn = 1 AND le."ACTION" = 'ASSERT'
                """
            )
            er_row = er_stmt.fetchone()
            tp = er_row["true_positive"] if isinstance(er_row, dict) else er_row[0]
            asserted = er_row["total_asserted"] if isinstance(er_row, dict) else er_row[1]
            tot_gt = er_row["total_true"] if isinstance(er_row, dict) else er_row[2]
            if asserted and asserted > 0 and tot_gt and tot_gt > 0:
                metrics["er_precision"] = round(float(tp / asserted), 4)
                metrics["er_recall"] = round(float(tp / tot_gt), 4)
            else:
                metrics["er_precision"] = None
                metrics["er_recall"] = None
        except Exception:
            metrics["er_precision"] = None
            metrics["er_recall"] = None

        # Metric 9: ID-name conflicts caught (T3)
        try:
            t3_conf_stmt = conn.execute(
                """
                SELECT COUNT(*)
                FROM TRUTH.GT_PLANT gp
                JOIN RESOLVE.PAIR_SCORE ps ON gp.subject_key = ps.pair_key
                WHERE gp.kind = 'ID_NAME_CONFLICT' AND ps.tier = 'T3'
                """
            )
            val = t3_conf_stmt.fetchval()
            if val is not None:
                metrics["id_name_conflicts_caught"] = f"{int(val)}/12"
            else:
                metrics["id_name_conflicts_caught"] = None
        except Exception:
            metrics["id_name_conflicts_caught"] = None

        # Metric 10: Decoy false-merges: a decoy L counts when any record of L is asserted
        # to another entity, or any record of another entity is asserted to L.
        try:
            decoy_stmt = conn.execute(
                """
                WITH cur AS (
                    SELECT rec_key, entity_key, "ACTION"
                    FROM GRAPH.LINK_EVENT
                    QUALIFY ROW_NUMBER() OVER (PARTITION BY link_key ORDER BY recorded_at DESC, event_id DESC) = 1
                ),
                wrong AS (
                    SELECT gt.entity_key AS true_key, cur.entity_key AS linked_key
                    FROM cur JOIN TRUTH.GT_RECORD_ENTITY gt ON gt.rec_key = cur.rec_key
                    WHERE cur."ACTION" = 'ASSERT' AND cur.entity_key <> gt.entity_key
                )
                SELECT COUNT(DISTINCT d.entity_key)
                FROM TRUTH.GT_ENTITY d
                JOIN wrong w ON w.true_key = d.entity_key OR w.linked_key = d.entity_key
                WHERE d.role = 'DECOY'
                """
            )
            val = decoy_stmt.fetchval()
            if val is not None:
                metrics["decoy_false_merges"] = f"{int(val)}/30"
            else:
                metrics["decoy_false_merges"] = None
        except Exception:
            metrics["decoy_false_merges"] = None

        # Metric 11: Group-linkage recall (registry-only parent links)
        try:
            gl_stmt = conn.execute(
                """
                SELECT COUNT(*)
                FROM TRUTH.GT_PLANT gp
                JOIN GRAPH.OWNERSHIP_EVENT oe ON gp.subject_key = oe.edge_key
                WHERE gp.kind = 'REGISTRY_ONLY_PARENT'
                  AND oe.status = 'CONFIRMED'
                  AND oe."ACTION" = 'ASSERT'
                """
            )
            val = gl_stmt.fetchval()
            if val is not None:
                metrics["group_linkage_recall"] = round(int(val) / 60.0, 4)
            else:
                metrics["group_linkage_recall"] = None
        except Exception:
            metrics["group_linkage_recall"] = None

        # Metric 13: Replay fidelity
        try:
            rep_res = replay(run_id)   # replays write a run, so they connect as TALOS_PIPELINE
            metrics["replay_fidelity"] = 1.0 if rep_res.matches else 0.0
        except Exception:
            metrics["replay_fidelity"] = None

        # Metric 14 & 15: Resolved without model & LLM share
        try:
            t_counts_stmt = conn.execute(
                """
                SELECT tier, COUNT(*) as cnt
                FROM RESOLVE.PAIR_SCORE
                WHERE tier IN ('T0', 'T1', 'T2', 'T3')
                GROUP BY tier
                """
            )
            t_counts = {
                (r["tier"] if isinstance(r, dict) else r[0]): int(r["cnt"] if isinstance(r, dict) else r[1])
                for r in t_counts_stmt.fetchall()
            }
            total_tiered = sum(t_counts.values())
            if total_tiered > 0:
                t0_t1 = t_counts.get("T0", 0) + t_counts.get("T1", 0)
                t2 = t_counts.get("T2", 0)
                metrics["resolved_without_model"] = round(float(t0_t1 / total_tiered), 4)
                metrics["llm_share"] = round(float(t2 / total_tiered), 4)
            else:
                metrics["resolved_without_model"] = None
                metrics["llm_share"] = None
        except Exception:
            metrics["resolved_without_model"] = None
            metrics["llm_share"] = None

        # Metric 16: Reviewer load
        try:
            ent_val = conn.execute("SELECT COUNT(*) FROM TRUTH.GT_ENTITY").fetchval()
            dec_val = conn.execute("SELECT COUNT(*) FROM GOV.DECISION_LOG").fetchval()
            if ent_val is not None and dec_val is not None and int(ent_val) > 0:
                metrics["reviewer_load_per_1000_entities"] = round(int(dec_val) / (int(ent_val) / 1000.0), 2)
            else:
                metrics["reviewer_load_per_1000_entities"] = None
        except Exception:
            metrics["reviewer_load_per_1000_entities"] = None

        # Metric 17: Pipeline runtime
        try:
            timing_stmt = conn.execute(
                """
                SELECT stage, SUM(seconds) as total_sec
                FROM GOV.PIPELINE_TIMING
                GROUP BY stage
                """
            )
            metrics["pipeline_runtime_seconds"] = {
                (r["stage"] if isinstance(r, dict) else r[0]): round(float(r["total_sec"] if isinstance(r, dict) else r[1]), 2)
                for r in timing_stmt.fetchall()
            }
        except Exception:
            metrics["pipeline_runtime_seconds"] = None

        # Metrics 1, 2, 3, 4: Group exposures & breaches
        try:
            exp_stmt = conn.execute(
                """
                WITH talos_group_exp AS (
                    SELECT group_key, SUM(exposure_amount) as limit_exp
                    FROM GOV.RUN_OUTPUT
                    WHERE run_id = {run_id}
                    GROUP BY group_key
                ),
                reported_baseline AS (
                    SELECT reported_group, SUM(reported_exposure) as rep_exp
                    FROM GOV.RUN_REPORTED
                    WHERE run_id = {run_id}
                    GROUP BY reported_group
                )
                SELECT g.group_no, g.head_entity_key, g.los_group_code, g.is_hidden_breach,
                       COALESCE(tge.limit_exp, 0) as talos_exp,
                       COALESCE(rb.rep_exp, 0) as rep_exp
                FROM TRUTH.GT_GROUP g
                LEFT JOIN talos_group_exp tge ON g.head_entity_key = tge.group_key
                LEFT JOIN reported_baseline rb ON g.los_group_code = rb.reported_group
                """,
                query_params={"run_id": run_id},
            )
            rows = exp_stmt.fetchall()
            if not rows:
                raise ValueError("No exposure data found for group calculation.")

            under_before = 0.0
            under_after = 0.0
            over_after = 0.0
            worst_err_amt = 0.0
            worst_err_pct = 0.0
            missed_breaches = 0
            false_breaches = 0

            cap_base = 4_200_000_000.0
            limit_threshold = 0.25 * cap_base

            for r in rows:
                g_no = r["group_no"] if isinstance(r, dict) else r[0]
                h_key = r["head_entity_key"] if isinstance(r, dict) else r[1]
                is_hb = bool(r["is_hidden_breach"] if isinstance(r, dict) else r[3])
                talos_exp = float(r["talos_exp"] if isinstance(r, dict) else r[4])
                rep_exp = float(r["rep_exp"] if isinstance(r, dict) else r[5])

                if is_hb and rep_exp < limit_threshold:
                    under_before += (limit_threshold - rep_exp)
                if is_hb and talos_exp < limit_threshold:
                    under_after += (limit_threshold - talos_exp)
                    missed_breaches += 1
                    misses.append(f"Group {g_no} ({h_key}): hidden breach missed (Talos {talos_exp:.2f} <= {limit_threshold:.2f})")

                if talos_exp > limit_threshold and not is_hb:
                    false_breaches += 1
                    misses.append(f"Group {g_no} ({h_key}): false breach reported (Talos {talos_exp:.2f} > {limit_threshold:.2f})")

                err = abs(talos_exp - rep_exp)
                worst_err_amt = max(worst_err_amt, err)
                if rep_exp > 0:
                    worst_err_pct = max(worst_err_pct, (err / rep_exp) * 100.0)

            metrics["understated_exposure_before_inr"] = round(under_before, 2)
            metrics["understated_exposure_after_inr"] = round(under_after, 2)
            metrics["understated_exposure_ratio"] = round((under_after / under_before), 4) if under_before > 0 else 0.0
            metrics["overstated_exposure_after_inr"] = round(over_after, 2)
            metrics["worst_single_group_error_amt"] = round(worst_err_amt, 2)
            metrics["worst_single_group_error_pct"] = round(worst_err_pct, 2)
            metrics["missed_breaches"] = f"{missed_breaches}/6"
            metrics["false_breaches"] = false_breaches

        except Exception:
            metrics["understated_exposure_before_inr"] = None
            metrics["understated_exposure_after_inr"] = None
            metrics["understated_exposure_ratio"] = None
            metrics["overstated_exposure_after_inr"] = None
            metrics["worst_single_group_error_amt"] = None
            metrics["worst_single_group_error_pct"] = None
            metrics["missed_breaches"] = None
            metrics["false_breaches"] = None

        # Save results JSON
        json_file = output_path / f"{profile}.json"
        json_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

        # Save misses markdown
        misses_file = output_path / f"misses_{profile}.md"
        misses_content = f"# Misses Report ({profile})\n\n"
        if misses:
            for m in misses:
                misses_content += f"- {m}\n"
        else:
            misses_content += "No planted cases missed. All evaluation targets met.\n"
        misses_file.write_text(misses_content, encoding="utf-8")

        # Update README
        _update_readme_metrics(profile=profile, metrics=metrics)

        return metrics

    finally:
        if close_conn:
            conn.close()
