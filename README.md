LitAssist

A personal literature review assistant, built first for PhD work on IVF and ICSI outcomes in sub-Saharan Africa. It runs on your own Windows laptop and opens in your web browser. It takes a review from search to first draft: search, screen, full text, charting and reporting.

What it does

Protocol. Each project holds the review question, review type, the PCC framework (Population, Concept, Context), inclusion and exclusion criteria, and the exclusion reasons offered during screening. A template sets up the PhD Objective 1 scoping review, with a draft search strategy and charting form.

Search. PubMed (NCBI E-utilities), Europe PMC (titles and abstracts, including preprints) and OpenAlex (strong on statistics journals and African outlets). You can check the hit count before downloading and set year limits. You can also import RIS, PubMed (.nbib) and CSV files, for example exports from African Journals Online, Google Scholar (through Publish or Perish), Scopus, Zotero or Mendeley. Duplicates across all sources are matched by PMID, DOI and title and skipped. Citation chasing finds the references of an included paper and the papers that cite it. Every search and import is logged, and a single button re-runs all saved searches to pick up new papers.

Screening. Title and abstract screening, one record at a time, with keyboard shortcuts: I include, M maybe, E exclude, A accept the AI suggestion, N next, P previous. Every exclusion needs a reason, and every decision is time stamped. AI suggestions (Gemini, with Claude as backup) give include, maybe or exclude with a reason and the criterion used. The app shows how often the AI agreed with you and warns if it suggested excluding anything you kept. A blind second screener mode lets a colleague screen a sample, and the app reports percentage agreement and Cohen's kappa and lists the disagreements to resolve.

Full text. Free, legal full texts are fetched from Europe PMC and Unpaywall. Paywalled papers can be uploaded as PDFs. Full text decisions are recorded with their own exclusion reasons.

Charting. An editable charting form (the Objective 1 form covers denominators, unit of analysis, handling of repeated cycles, statistical methods and more). The AI drafts each value with the exact supporting quote from the paper. LitAssist checks every quote against the text and flags any it cannot find. You check and save each form.

Report. A PRISMA-ScR flow diagram that updates as you work, a search methods paragraph written from the search log, and a first draft of the synthesis as a Word document. The draft may cite only included sources: every citation is checked, invalid ones are removed, and the reference list is built from your records, not by the AI.

Export. RIS for Zotero or Mendeley, BibTeX, sending straight to a Zotero collection, and an Excel workbook with records, charting, search log, PRISMA-ScR counts and protocol. There is also a backup zip of all your work (API keys are left out).

Installing on Windows

Step 1. Install Python 3.11 or newer from python.org/downloads. On the first screen of the installer, tick "Add python.exe to PATH", then click Install Now.

Step 2. On this GitHub page, click the green Code button, then Download ZIP. Right click the downloaded file, choose Extract All, and put the folder somewhere permanent, for example Documents\LitAssist-app.

Step 3. Open the extracted folder and double click install.bat. If Windows shows a blue "Windows protected your PC" box, click More info, then Run anyway. Installation takes a few minutes and creates a LitAssist shortcut on your desktop.

Step 4. Double click the LitAssist shortcut. A black window opens (keep it open while you work) and the app opens in your browser. Close the black window when you are finished.

Updating to a new version

Close the black LitAssist window. Download the ZIP again, extract it into the same folder and choose to replace the files. Then double click install.bat again, because new versions can need new components. Your projects are stored separately and are not touched.

First time setup

Open the Settings tab. Enter your email address, which PubMed, Europe PMC and Unpaywall ask for. For AI features, add a Gemini API key (from aistudio.google.com) and, as a backup, an Anthropic API key (from platform.claude.com/settings/keys). Optional extras are a free NCBI API key (faster PubMed), a free OpenAlex API key (needed if OpenAlex says its shared allowance is used up) and a Zotero user ID and key. Use the Test buttons to check each one. Paste keys only into the app, never into a chat or document.

Your data

Projects, records, decisions, full texts and settings are stored in Documents\LitAssist on your laptop, not in this code folder. Use Export, Back up your work regularly and keep the zip on Google Drive.

For developers

Install requirements-dev.txt and run python -m pytest. Start the app with streamlit run app.py. Set the LITASSIST_HOME environment variable to keep data somewhere other than Documents\LitAssist. The code is in litassist/ (logic) and litassist/ui/ (one module per tab).
