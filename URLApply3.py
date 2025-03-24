import asyncio
import json
import os
from datetime import datetime
from typing import Optional, List, Dict

from pydantic import BaseModel, EmailStr, HttpUrl
from playwright.async_api import async_playwright, TimeoutError
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key="sk-YOUR-OPENAI-API-KEY")


# ==========================
# 🚀 Pydantic Models
# ==========================

class User(BaseModel):
    id: int
    username: str
    email: EmailStr
    password_hash: str
    created_at: datetime
    updated_at: datetime


class Profile(BaseModel):
    user_id: int
    full_name: Optional[str]
    email: Optional[EmailStr]
    phone: Optional[str]
    resume_url: Optional[HttpUrl]
    linkedin_url: Optional[HttpUrl]
    github_url: Optional[HttpUrl]
    portfolio_url: Optional[HttpUrl]
    created_at: datetime
    updated_at: datetime


class UserCustomField(BaseModel):
    id: int
    user_id: int
    field_name: str
    field_value: str
    created_at: datetime
    updated_at: datetime


class JobApplication(BaseModel):
    id: int
    user_id: int
    job_url: str
    status: str  # ENUM in DB
    company_name: Optional[str]
    job_title: Optional[str]
    applied_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class JobApplicationResponse(BaseModel):
    id: int
    application_id: int
    field_name: str
    field_value: str
    created_at: datetime
    updated_at: datetime


# ==========================
# 🔥 Helper Functions
# ==========================

def get_merged_user_info(profile: Profile, custom_fields: List[UserCustomField]) -> Dict[str, str]:
    """Merge user profile and custom fields into a single dictionary."""
    user_info = {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "resume_url": profile.resume_url,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "portfolio_url": profile.portfolio_url,
    }
    user_info = {k: v for k, v in user_info.items() if v}  # Remove None values

    for field in custom_fields:
        user_info[field.field_name.lower()] = field.field_value

    return user_info


# ==========================
# 🕵️‍♂️ Playwright Form Autofill
# ==========================

async def fill_and_submit_form(url, user_info):
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1280, "height": 1024})

            try:
                await page.goto(url, timeout=10000)
            except TimeoutError:
                print("Page load timed out, but continuing...")

            await page.wait_for_timeout(2000)

            # Extract form fields
            form_structure = await page.evaluate('''() => {
                const fields = [];
                
                function getLabel(element) {
                    return document.querySelector(`label[for="${element.id}"]`)?.textContent.trim() || 
                           element.closest('label')?.textContent.trim() || 
                           element.placeholder || 
                           element.name || '';
                }
                
                document.querySelectorAll('input[type="text"], input[type="email"], textarea').forEach(input => {
                    if (input.type === 'hidden') return;
                    fields.push({
                        type: 'input',
                        inputType: input.type || 'text',
                        label: getLabel(input),
                        id: input.id || '',
                        name: input.name || '',
                        placeholder: input.placeholder || '',
                        selector: input.id ? `#${input.id}` : `[name="${input.name}"]`,
                        required: input.required
                    });
                });

                document.querySelectorAll('select').forEach(select => {
                    const options = Array.from(select.options).map(opt => ({
                        value: opt.value,
                        text: opt.text.trim(),
                        selected: opt.selected
                    }));
                    fields.push({
                        type: 'select',
                        label: getLabel(select),
                        id: select.id || '',
                        name: select.name || '',
                        options,
                        selector: select.id ? `#${select.id}` : `[name="${select.name}"]`,
                        required: select.required
                    });
                });

                return fields;
            }''')

            print("\nFound form fields:", json.dumps(form_structure, indent=2))

            # Analyze fields using GPT
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": "Map form fields to user data based on semantics."
                    },
                    {
                        "role": "user",
                        "content": f"""
                        User info: {json.dumps(user_info, indent=2)}
                        Form fields: {json.dumps(form_structure, indent=2)}
                        Return JSON mapping form fields to values.
                        """
                    }
                ]
            )

            ai_response = json.loads(response.choices[0].message.content.strip())
            field_mapping = ai_response.get("field_mapping", {})
            unknown_questions = ai_response.get("unknown_questions", [])

            print("\nAI Mappings:", json.dumps(field_mapping, indent=2))
            print("\nUnknown Fields:", json.dumps(unknown_questions, indent=2))

            # Fill form fields
            for selector, value in field_mapping.items():
                try:
                    element = await page.wait_for_selector(selector, timeout=3000)
                    element_type = await page.evaluate("el => el.tagName.toLowerCase()", element)
                    
                    if element_type == 'select':
                        await element.select_option(value=value)
                    else:
                        await element.fill(value)

                    print(f"Filled {selector} with {value}")

                except Exception as e:
                    print(f"Error filling {selector}: {e}")

            # Submit form (if a submit button exists)
            try:
                submit_button = await page.query_selector('button[type="submit"], input[type="submit"]')
                if submit_button:
                    await submit_button.click()
                    print("Form submitted successfully.")
                else:
                    print("No submit button found.")
            except Exception as e:
                print(f"Submit error: {e}")

            await page.wait_for_timeout(3000)

        except Exception as e:
            print(f"Error during form filling: {e}")
        finally:
            await browser.close()


# ==========================
# 🎯 Main Execution
# ==========================

if __name__ == "__main__":
    url = "https://example-job-form.com"
    
    profile = Profile(
        user_id=1,
        full_name="John Doe",
        email="john.doe@example.com",
        phone="123-456-7890",
        resume_url="file:///path/to/resume.pdf",
        linkedin_url="https://linkedin.com/in/johndoe",
        github_url="https://github.com/johndoe",
        portfolio_url=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    custom_fields = [
        UserCustomField(id=1, user_id=1, field_name="Availability Date", field_value="2025-04-01", created_at=datetime.utcnow(), updated_at=datetime.utcnow()),
        UserCustomField(id=2, user_id=1, field_name="Salary Expectations", field_value="200k", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    ]

    user_info = get_merged_user_info(profile, custom_fields)

    asyncio.run(fill_and_submit_form(url, user_info))
