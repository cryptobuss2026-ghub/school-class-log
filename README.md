# Weekly Teacher Class Log (Streamlit + Google Sheets + n8n)

## Files
| File | Purpose |
|---|---|
| `app.py` | Streamlit app: Register, Log Lessons, Admin tabs |
| `requirements.txt` | Python dependencies |
| `secrets.toml.example` | Template for `.streamlit/secrets.toml` / Streamlit Cloud secrets |
| `n8n_weekly_report_workflow.json` | Importable n8n workflow (weekly email to Headmistress) |

## 1. Google Service Account
1. Go to https://console.cloud.google.com and create (or pick) a project.
2. **APIs & Services > Library** > enable **Google Sheets API**.
3. **APIs & Services > Credentials > Create credentials > Service account**. Name it, skip optional steps.
4. Open the service account > **Keys > Add key > Create new key > JSON**. A JSON file downloads. Keep it private.
5. Copy the `client_email` value from that JSON.

## 2. Create the Google Sheets
1. Create one spreadsheet named `Teachers_Register` (leave empty; the app creates the `Teachers` tab and headers).
2. Create one spreadsheet per section: `Grade_1_Sec_A`, `Grade_1_Sec_B`, ... (leave empty; the app creates the `Log` tab and headers).
3. **Share every one of these spreadsheets with the service account's `client_email` as Editor.**
4. Copy each spreadsheet ID from its URL: `https://docs.google.com/spreadsheets/d/<THIS_PART>/edit`.

## 3. Configure secrets
Copy `secrets.toml.example` to `.streamlit/secrets.toml` and fill in:
* `[sheets] teachers_register_id` and every entry under `[section_sheets]`
  (label format `"Grade 1 - Sec A"`; add or remove lines to match your school)
* `[admin] password`
* `[gcp_service_account]` from the JSON key. Keep `private_key` on one line with `\n` escapes.

Local run:
```
pip install -r requirements.txt
streamlit run app.py
```

## 4. Deploy on Streamlit Cloud
1. Push `app.py`, `requirements.txt` (NOT secrets) to a GitHub repo.
2. https://share.streamlit.io > New app > pick repo, main file `app.py`.
3. **Advanced settings > Secrets**: paste the full contents of your `secrets.toml`.
4. Deploy. Share the URL with teachers.

## 5. n8n workflow
1. n8n > Workflows > **Import from file** > `n8n_weekly_report_workflow.json`.
2. Nodes (in order):
   1. **Sunday 00:05 Trigger** - cron `5 0 * * 0`, workflow timezone `Asia/Karachi`
   2. **Define Sections** - edit the list: section label + sheet ID for each section
   3. **Read Section Log** - Google Sheets "Get Row(s)", tab `Log`; attach Google Sheets OAuth2 credentials
   4. **Build HTML Report** - filters to the current week, groups by section, lists sections with no submissions
   5. **Email Headmistress** - Gmail node; set the `sendTo` address and attach Gmail OAuth2 credentials
3. Click **Execute workflow** once to test, then toggle the workflow **Active**.

### Why Sunday 00:05 and not Saturday 11:59 PM?
Teachers can submit until 23:59:59 on Saturday. A trigger at exactly 23:59 would miss last-minute entries.
To use Saturday 23:59 anyway, change the cron to `59 23 * * 6` and remove `.minus({ minutes: 30 })` in the Build HTML Report node.

## Behaviour notes
* Week label format is ISO, e.g. `2026-W41` (Mon-Sun), stored in the "Week Number" column.
* Submissions are blocked all day Sunday and re-checked at the moment of submit.
* Teachers' PINs are stored as salted PBKDF2 hashes, never in plain text.
* Entries are written with `RAW` mode so text starting with `=` cannot run as a spreadsheet formula.
* Teachers may submit several entries per week (e.g. one per subject or section).
