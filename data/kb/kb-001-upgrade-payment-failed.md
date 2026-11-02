---
id: KB-001
title: Payment failed or plan not upgraded after paying
tags: billing, payment, upgrade, pro, card, declined, failed, charge, pending, plan
---
## Symptoms
- "Payment failed" shown when upgrading to Pro.
- The customer was charged (or sees a pending charge) but the account still shows the Free plan.

## Why it happens
Each upgrade attempt places an authorization on the card. If the payment provider or our provisioning webhook
times out, the authorization can stay pending while the plan is not upgraded. Retrying creates another
authorization, so several retries can show up as several pending charges.

## What support does
1. Check the customer's billing transactions and upgrade status.
2. If any charge is pending or captured without a plan change, hand the ticket to the **billing team**.
   Billing can manually apply the plan and void or refund the duplicate authorizations.
3. While billing investigates, support may grant a **temporary 24-hour Pro trial** so the customer is not blocked.
4. Tell the customer not to retry the payment again until billing confirms.

## What not to say
Do not promise a refund date. Pending authorizations are usually released by the bank in 3-7 business days,
but timing depends on the customer's bank.
