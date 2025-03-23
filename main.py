
"""
Goal: Searches for job listings, evaluates relevance based on a CV, and applies
@dev You need to add OPENAI_API_KEY to your environment variables.
Also install required packages: pip install openai langchain-openai
"""

import csv
import os
import sys
from pathlib import Path
import logging
from typing import List, Optional
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from PyPDF2 import PdfReader
from langchain_openai import ChatOpenAI  # Changed import
from pydantic import BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.context import BrowserContext
from browser_use.browser.browser import Browser, BrowserConfig

# Validate OpenAI environment variable
# load_dotenv()
# required_env_vars = ["OPENAI_API_KEY"]  # Changed to OpenAI key
# for var in required_env_vars:
#     if not os.getenv(var):
#         raise ValueError(f"{var} is not set. Please add it to your .env file.")

logger = logging.getLogger(__name__)
controller = Controller()

# CV = Path.cwd() / 'cv_04_24.pdf'
CV = Path(__file__).parent / 'resume' / 'Chandrahas_Fullstack_A.pdf'
if not CV.exists():
    raise FileNotFoundError(f'CV file not found at {CV}')

class Job(BaseModel):
    title: str
    link: str
    company: str
    fit_score: float
    location: Optional[str] = None
    salary: Optional[str] = None

@controller.action('Save jobs to file - with a score how well it fits to my profile', param_model=Job)
def save_jobs(job: Job):
	with open('jobs.csv', 'a', newline='') as f:
		writer = csv.writer(f)
		writer.writerow([job.title, job.company, job.link, job.salary, job.location])

	return 'Saved job to file'


@controller.action('Read jobs from file')
def read_jobs():
	with open('jobs.csv', 'r') as f:
		return f.read()


@controller.action('Read my cv for context to fill forms')
def read_cv():
	pdf = PdfReader(CV)
	text = ''
	for page in pdf.pages:
		text += page.extract_text() or ''
	logger.info(f'Read cv with {len(text)} characters')
	return ActionResult(extracted_content=text, include_in_memory=True)


@controller.action(
	'Upload cv to element - call this function to upload if element is not found, try with different index of the same upload element',
)
async def upload_cv(index: int, browser: BrowserContext):
	path = str(CV.absolute())
	dom_el = await browser.get_dom_element_by_index(index)

	if dom_el is None:
		return ActionResult(error=f'No element found at index {index}')

	file_upload_dom_el = dom_el.get_file_upload_element()

	if file_upload_dom_el is None:
		logger.info(f'No file upload element found at index {index}')
		return ActionResult(error=f'No file upload element found at index {index}')

	file_upload_el = await browser.get_locate_element(file_upload_dom_el)

	if file_upload_el is None:
		logger.info(f'No file upload element found at index {index}')
		return ActionResult(error=f'No file upload element found at index {index}')

	try:
		await file_upload_el.set_input_files(path)
		msg = f'Successfully uploaded file "{path}" to index {index}'
		logger.info(msg)
		return ActionResult(extracted_content=msg)
	except Exception as e:
		logger.debug(f'Error in set_input_files: {str(e)}')
		return ActionResult(error=f'Failed to upload file to index {index}')


# browser = Browser(
#     config=BrowserConfig(
# 		disable_security=True,
#         headless=False,  # Set to True if you don't need visual browser
# 		browser_instance_path = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs"
#     )
# )
# help(BrowserConfig)

browser = Browser(
    config=BrowserConfig(
        # Specify the path to your Chrome executable
        chrome_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # macOS path
        # For Windows, typically: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
        # For Linux, typically: '/usr/bin/google-chrome'
    )
)

async def main():
    ground_task = (
        'You are a professional job finder. '
        '1. Read my cv with read_cv '
        '2. Find fullstack engineer roles and save them to a file '
        '3. Search at company:'
    )
    tasks = [
        ground_task + '\n' + 'Adobe',
        # Add other tasks as needed
    ]
    
    # Use OpenAI model instead of Azure
    model = ChatOpenAI(
        model="gpt-3.5-turbo",  # or "gpt-4"
        openai_api_key="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"
    )

    agents = []
    for task in tasks:
        agent = Agent(task=task, llm=model, controller=controller, browser=browser)
        agents.append(agent)

    await asyncio.gather(*[agent.run() for agent in agents])

if __name__ == "__main__":
    asyncio.run(main())
