LitAssist

A personal literature search and screening assistant, built first for PhD work on IVF and ICSI outcomes in sub-Saharan Africa. It runs on your own Windows laptop and opens in your web browser.

What it does now (phase 1, part 1)

Projects with a written protocol: review question, review type, the PCC framework (Population, Concept, Context), and inclusion and exclusion criteria. A ready made template sets up the PhD Objective 1 scoping review with a draft PubMed search strategy.

PubMed searching through the NCBI E-utilities API. You can check the number of hits before downloading, limit by year, and retrieve full records with abstracts, authors, MeSH terms and DOIs. Duplicates are skipped automatically.

A search log that records every search string, date, database and count, ready for the methods section.

Title and abstract screening, one record at a time: include, maybe or exclude, with a required reason for every exclusion. Every decision is time stamped and kept in a history.

Exports: RIS for Zotero or Mendeley, BibTeX, and an Excel workbook with the records, search log, PRISMA-ScR counts and protocol. Records can also be sent straight into a Zotero collection.

Coming next: AI assisted screening with reasons (needs the Anthropic API key), more databases (Europe PMC, OpenAlex), file imports from African Journals Online and Google Scholar, full text handling and the charting form.

Installing on Windows

Step 1. Install Python 3.11 or newer from python.org/downloads. On the first screen of the installer, tick "Add python.exe to PATH", then click Install Now.

Step 2. On this GitHub page, click the green Code button, then Download ZIP. Right click the downloaded file, choose Extract All, and put the folder somewhere permanent, for example Documents\LitAssist-app.

Step 3. Open the extracted folder and double click install.bat. If Windows shows a blue "Windows protected your PC" box, click More info, then Run anyway. Installation takes a few minutes and creates a LitAssist shortcut on your desktop.

Step 4. Double click the LitAssist shortcut. A black window opens (keep it open while you work) and the app opens in your browser. Close the black window when you are finished.

First time setup

Open the Settings tab. Enter your email address, which NCBI asks for. Optionally add a free NCBI API key, which makes large searches faster. To send records to Zotero, add your Zotero user ID and a Zotero API key with write access, both from zotero.org/settings/keys. Use the Test buttons to check each connection.

Your data

Projects, records, decisions and settings are stored in Documents\LitAssist on your laptop, not in this code folder. Back that folder up (for example to Google Drive) to keep your work safe. Keys are stored only in that folder and are never uploaded to GitHub.

For developers

Install requirements-dev.txt and run python -m pytest. Start the app with streamlit run app.py. Set the LITASSIST_HOME environment variable to keep data somewhere other than Documents\LitAssist.
