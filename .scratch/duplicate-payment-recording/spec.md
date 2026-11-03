# Spec: Duplicate Payment Recording

Status: ready-for-agent

Source: tab "Duplicate Payment Recorded" of https://docs.google.com/document/d/14lNlney4bLIOfOdG5UTpa52L7ZFIipWY4FzPlV-KGwU/edit?tab=t.b5f32zhxjcv4, refined in a grilling session on 2026-10-28. Baseline: `main` at v1.0.0. Vocabulary follows `GLOSSARY.md`.

## Problem Statement

A learner pays for a course, the Payment entity charges them, and then the platform records the payment. Today, on v1.0.0:

- When the confirmation is processed twice at almost the same moment (for example a fast double click, or two polls of the waiting page), the platform no longer records two Transactions or two Receipts, but the learner is sent to an error/reconciliation page even though they paid, got a Receipt and are enrolled.
- When recording fails after the Transaction is saved and the Cart is marked as paid, but before the Receipt and the enrollment are created, the learner has paid and has neither. If they come back, they see an error again. Nothing completes it; only support can fix it by hand.
- The platform itself does not check that the amount and currency of the payment match the total of the Cart. That check depends entirely on each Payment processor, so a learner could be enrolled after paying less, or in another currency.

## Solution

Once a learner has paid, they always end up with exactly one Transaction, one Receipt and their enrollment, and they see that the payment was successful:

- Any further confirmation for a Purchase is ignored and the learner is shown the successful payment with their Receipt.
- If recording was interrupted after the Transaction was saved, the next time the learner's waiting page asks for the payment status, the platform completes the Receipt and the enrollment without creating another Transaction.
- A payment is only accepted when its amount and currency match the total of the Cart. When they do not match, the learner is not enrolled and sees a message saying what the problem was (amount or currency).
- All of this works the same for every Payment processor, because it lives in the shared step that records a confirmed payment.

## User Stories

1. As a learner, I want my payment recorded once even if the Payment entity confirms it more than once, so that I am not receipted twice.
2. As a learner, I want to see the successful payment page when I double click or reload while my payment is being recorded, so that I am not told something went wrong after paying.
3. As a learner, I want to see my Receipt when a repeated confirmation arrives for my Purchase, so that I have proof of payment.
4. As a learner, I want to be enrolled in the course after a successful payment, so that I get what I paid for.
5. As a learner paying at the same moment as another learner, I want my own unique Receipt number, so that my Purchase is not mixed with theirs.
6. As a learner paying at the same moment as another learner, I want to be enrolled, so that I am not left paid but without the course.
7. As a learner whose payment recording was interrupted by a platform failure, I want my Receipt and enrollment completed when I come back to the waiting page, so that I get what I paid for without contacting support.
8. As a learner whose payment recording was interrupted, I want no second Transaction created when it is completed, so that my payment is recorded only once.
9. As a learner who left before my payment was recorded, I want it recorded when I try to access or buy the course again, so that I still get the course I paid for.
10. As a learner, I want my payment rejected if it arrives in a different currency than the Cart, and to see a message about the currency problem, so that I know why I was not enrolled.
11. As a learner, I want my payment accepted when the amount is the same number written differently (100 vs 100.0), so that a correct payment is not rejected.
12. As a learner, I want a payment with a different amount than the Cart total rejected, and to see a message about the amount problem, so that I know why I was not enrolled.
13. As a learner paying with a Payment processor that does not send the currency, I want my payment still checked by amount, so that a correct payment is accepted.
14. As a support agent, I want a rejected payment kept as a failed Transaction with its reason, so that I can resolve it by hand.
15. As a support agent, I want a warning in the logs with the external payment id when a confirmation with a different payment id arrives for a Purchase, so that I can detect and refund a possible double charge.
16. As an operator, I want the database to refuse a second Receipt for the same Cart, so that a future bug cannot produce two Receipts for one Purchase.
17. As a developer of a Payment processor plugin, I want the amount and currency check done by the shared step, so that every processor gets it without implementing it.
18. As a developer of a Payment processor plugin, I want my processor-specific reconciliation to keep running after the shared check, so that processor-specific rules still apply.

## Implementation Decisions

- **Where:** all changes live in the shared step that records a confirmed payment (the base Payment processor's record-and-fulfil flow and the payment status view that triggers it from the waiting page). No change to how each Payment processor talks to its Payment entity.
- **Serialize per Cart:** the shared step locks the Cart row at its start and re-reads its status under that lock, instead of trusting the in-memory Cart. Two confirmations for the same Cart are processed one after the other.
- **Cart already paid:** if, under the lock, the Cart is already paid, no Transaction is created and the Cart is not changed, whatever the incoming payment id is (same id or a different one). A different external payment id is logged as a warning with that id. Then:
  - if the Cart has its Receipt, the outcome is `paid` with that Receipt;
  - if the Cart has a successful Transaction but no Receipt (interrupted recording), the existing issue-Receipt-and-enrol step runs, and the outcome is `paid` when it succeeds.
- **Duplicate and status-race errors:** the paths that today end in "not fulfilled" after a duplicate Transaction or a Cart status conflict resolve through the same "Cart already paid" rule above, so the learner sees `paid` when the Purchase exists.
- **Amount and currency check in the shared step**, before the processor's own reconciliation:
  - amount: the notified amount is parsed as a decimal and compared for exact numeric equality with the Cart total (100 == 100.0 == 100.00; no tolerance);
  - currency: compared with the Cart currency after the existing canonical mapping, only when the notice carries a currency; when it does not, only the amount is checked;
  - on mismatch: the Transaction is stored as failed with a reason naming the mismatch, the Cart follows the existing not-reconciled path (not paid, no Receipt, no enrollment), and the outcome distinguishes currency from amount so the learner sees a specific message;
  - the processor-specific reconciliation keeps running after this check.
- **New outcomes:** `currency_mismatch` and `amount_mismatch`, routed by the waiting page to a page that shows the specific message. Whether the message text is rendered by the core or must be supplied by each Payment processor is to be verified during implementation.
- **Schema:** a unique constraint on the Receipt's Cart (one Receipt per Cart), added with a migration.
- No new settings.

## Testing Decisions

- Tests check external behaviour only: the outcome returned to the waiting page, the number of Transactions and Receipts for the Cart, the Receipt numbers, and whether the learner is enrolled. They do not assert on locks, queries or internal calls.
- **Seam:** the payment status view, driven through the test Payment processor (dummy processor and its status view). One exception: the one-Receipt-per-Cart rule is tested at the model level.
- Write the acceptance-criteria tests first and run them against `main`; the ones that fail define the work. Expected today: AC1b, AC3, AC5 and AC6 fail; AC1a, AC2 and AC4 pass.
- Tests, one per acceptance criterion of the source document, plus the grilling decisions:
  - **AC1a** same confirmation polled twice in sequence → `paid` both times, 1 Transaction, 1 Receipt, enrolled.
  - **AC1b** second confirmation arrives while the first is in progress (stale Cart) → `paid` both times, 1 Transaction, 1 Receipt, enrolled.
  - **AC2** two learners' Carts confirmed interleaved → distinct Receipt numbers, both enrolled.
  - **AC3** confirmation in another currency → not enrolled, failed Transaction with reason, outcome `currency_mismatch`.
  - **AC4** amount `100.0` for a Cart total of `100` → `paid`, enrolled.
  - **AC5** amount `50` for a Cart total of `100` → rejected, not enrolled, failed Transaction, outcome `amount_mismatch`.
  - **AC6** Transaction saved and Cart paid but Receipt/enrollment failed, then the status is polled again → `paid`, 1 Receipt, enrolled, still 1 Transaction.
  - confirmation with a different external payment id for a paid Cart → ignored, no new Transaction, `paid`.
  - notice without currency → only the amount is checked.
  - second Receipt for the same Cart → refused by the database.
- Tests run on the current test database (SQLite). They do not prove real row locking; running them on MySQL is a later task.
- **Prior art:** status-view tests using the dummy status view and outcome assertions in the processor mixins tests; duplicate and Receipt-failure tests in the base processor tests; the invoice number sequence tests in the model tests.

## Out of Scope

- The race on the very first Receipt of a new invoice prefix (two payments at the exact moment the prefix's counter is created).
- Checking course capacity or closed enrollment after payment, and reserving a seat while the learner pays.
- Refunding a possible double charge with a different payment id (support handles it by hand).
- Recording payments without the learner returning (Payment entity webhooks or a periodic job). If the learner never comes back, nothing is recorded until they do.
- Running tests on MySQL and adding a MySQL service to CI with GitHub Actions.
- Coupons and taxes: today the Cart total equals the list price.

## Further Notes

- The source document was written against a local copy older than v1.0.0. v1.0.0 already prevents two Transactions with the same payment id, two Receipts through the paid-status transition, and duplicate Receipt numbers. If production still runs a version before 1.0.0, it still has the original bugs until it is upgraded.
- The one-Receipt-per-Cart migration will fail if a database already holds Carts with more than one Receipt (possible on deployments that ran versions before 1.0.0). Check for them before deploying.
- The "in-flight payment" flow already sends a learner who tries to buy the same course again back to the waiting page; together with AC6 this covers a learner who closed the browser or lost connection and comes back.
