# Cursor handoff

Branch `cursor/delegation-route-approval-contract-ac72`. Pull request https://github.com/aweass69-tech/hermes-agent/pull/1 is unmerged. Do not merge. Base before this work is `b200f5bc60`.

Unmerged commits, oldest first:

| Commit | What it is |
|---|---|
| `e3b2d563bb` | Misplaced delegate route refused; turn parent used. Mac-accepted. Do not rerun. |
| `b3b9ddf47e` | Manual approval blocks a dangerous command when nothing can prompt. Mac-accepted. Do not rerun. |
| `1a1aa02987` | Test: empty `plugins.enabled` hides user plugin tools. Doctor still loads the directory. |
| `5bcb246fe1` | Already-enabled plugin re-import asks the running gateway. |
| `a0eb8810d5` | Opt-in `review_contract`. Pass only from the review child's validated JSON. |
| `443bd3938c` | Zero-tool turn notice is not "send it again" and is not complete. |
| `ab9f8e934b` | Tool-bearing stop stamps `intake_diagnostic` on the closing assistant row. |
| `8be6a03a07` | `workflow: role_intake` requires requirements and a distinct artifact. Call-level `output_schema` on one task is applied. |

Another executor is applying `8be6a03a07` on the Mac. Do not apply it again. The empty-response counters below are not on that commit until this handoff commit is deployed.

## t1597 main intake

Public result only. Commit on the machine was `ab9f8e934b`. One masked role intake, 7390 bytes, not the public fixture. Main `gemma4:26b`, `--max-turns 6`. Result: `api_calls` 6, tools 0, `turn_exit_reason` `empty_response_exhausted`, `budget_used` 6/6, `completed` false, `failed` false. Work, review, and artifact were not reached. `failed` stays false. That is not a normal completion.

`final_response_chars` 137 is the English framework line `⚠️ No reply: gemma4:26b didn't produce a reply this time, even after retries...`. The saved 181-character assistant row is the zero-tool framework notice. Neither string is model text.

`empty_response_exhausted` is set only after visible content is empty. Six calls at this exit match one empty visible reply, two thinking prefills, and three empty retries. A single blank body would stop earlier. The 12b `repetition_loop` cutter is a different path and a different error string. No response body was kept, so this match does not prove the provider sent reasoning, `<think>` text, or a truly empty HTTP message. `_terminal_empty` returns `(empty)` in both the no-reasoning and the reasoning-discarded branches, then the explainer replaces it, so 137 cannot separate those branches.

The next empty turn records `intake_diagnostic.empty_observation`: prefill count, empty-retry count, reasoning character count, `reasoning_discarded`, visible character count, and finish reason. It does not store the text. It does not make the model emit a tool call.

## Local-first routines

Use files already under the profile home and `hermes cron`. Do not add a host SDK trigger or a Grok trigger. Do not create accounts. Do not change model names, context sizes, `plugins.enabled`, or approval mode.

Canonical role files, cron job ids, and the connected GitHub checkout list are local-only. Treat every concrete path that is not in the table below as unconfirmed.

| Known from the public t1597 packet | State |
|---|---|
| `~/.hermes/local-workflows/role-binding-t1597/native-cli/intake-source.json` | sha `1aa5b0980b619b9c3670d0d1d6230574825a7c618d673d1cd537504e55fd1fad` |
| `intake-requirements.txt` | sha `b0c01a908efe725e855719104a655d01eb4b7e8997b0384cb23e8284018d8687` |
| `intake-draft.json` | absent before work. sha unconfirmed |
| Config sha `b3053895e14ea5e8043381f562561af8b05fc6c98b6b275b587543e84e8c354e` | unchanged across that run |
| `SCHEDULE.md:38` | task id only. File body is not in this repo |

Parent paused all seven routines. Leave them paused until the cutover executor turns a Hermes cron job on. Do not re-ask Grok and do not open Box.

## Worklist

Do not invent titles for the local thirteen. `new_whole13_goals_completed` is empty. `SCHEDULE.md` is unconfirmed here.

1. Let the apply executor finish `8be6a03a07`. Do not repeat it.
2. Let the archive executor finish the local copy. Do not export a private packet.
3. Let the cutover executor move paused routines onto Hermes cron. Keep them paused until that executor enables one.
4. Deploy the empty-observation commit. One Mac check below. VM cannot call Ollama.
5. After that check, one role-intake run only if `empty_observation` shows the endpoint returned a visible reply on the probe. Use `tests/fixtures/reviewed_workflow/role-intake-oneshot.txt`, not the private packet.
6. Do not rerun e3 routes, b3 approval, or the review-contract cache suite.
7. `repetition_loop` on a 12b child is identified and not fixed. Cause unconfirmed. Do not retry that private work.
8. Release stays `owner_authorization_required`. Do not simulate owner approval.
9. AutoOntology stays paused. Do not start it.
10. Desktop and ego stay blocked. Do not start them.
11. Plugin list stays the live list. `local-fixed-role-tools` is required for its five tools. `advanced-delegation` keeps the accepted routes. `platforms/telegram` is not required for this CLI intake.
12. Preserve local GitHub checkouts already on disk. Which remotes are connected is unconfirmed. Do not clone or fetch.
13. Read `intake_diagnostic` from `hermes sessions export` after every native CLI stop. `role_intake_bound: true` is the only role-intake binding mark. `review_accepted` still requires the review child.

## One Mac acceptance

Restart the gateway onto the handoff commit only. New CLI session. Send one short public line: `Reply with the single word pong. Do not call tools.`

- A normal `pong` means the endpoint answered. The role-intake empty was not "the model never responds." Do not resend the private intake in this step.
- `empty_response_exhausted` again: copy only `intake_diagnostic`, including `empty_observation`. `reasoning_discarded: true` means the last reply had reasoning and Hermes did not show it. `reasoning_discarded: false` with `reasoning_chars: 0` means the last reply had no reasoning text. Stop there.

## Must run on the Mac

Ollama calls, gateway restart, session export, role files, cron cutover, archive, and anything under `~/.hermes`. This VM can run the offline tests only.
