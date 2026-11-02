---
id: KB-013
title: CSV import errors and limits
tags: csv, import, upload, file too large, imp-413, imp-415, error, crm, data import
---
| Error | Meaning | Fix |
|---|---|---|
| IMP-413 | File larger than 50 MB | Split the file into parts under 50 MB, or zip it (zipped CSV up to 200 MB is accepted) |
| IMP-415 | Not UTF-8 encoded | Re-export as "CSV UTF-8" |
| IMP-422 | Missing header row | Make the first row column names |

Imports run in the background. Large imports can take up to 10 minutes, and an email is sent when they finish.
