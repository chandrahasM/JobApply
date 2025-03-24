import asyncio
import json
import os
from playwright.async_api import async_playwright, TimeoutError
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key="KEY")

async def fill_and_submit_form(url, user_info):
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1280, "height": 1024})

            try:
                await page.goto(url, timeout=10000)
            except TimeoutError:
                print("Page load timed out, but continuing anyway...")
            
            await page.wait_for_timeout(2000)
            
            # Get form structure including dropdowns and file inputs
            form_structure = await page.evaluate('''() => {
                const formFields = [];
                
                function getFieldDescription(element) {
                    const label = document.querySelector(`label[for="${element.id}"]`)?.textContent.trim() || 
                                element.closest('label')?.textContent.trim() || 
                                element.placeholder || 
                                element.name || '';
                                
                    const parentText = element.parentElement?.textContent.trim() || '';
                    return { label, parentText };
                }
                
                // Text inputs and textareas
                document.querySelectorAll('input[type="text"], input[type="email"], input:not([type]), textarea').forEach(input => {
                    if (input.type === 'hidden') return;
                    const { label, parentText } = getFieldDescription(input);
                    formFields.push({
                        type: 'input',
                        inputType: input.type || 'text',
                        label, parentText,
                        id: input.id || '',
                        name: input.name || '',
                        placeholder: input.placeholder || '',
                        selector: input.id ? `#${input.id}` : input.name ? `[name="${input.name}"]` : `input[type="${input.type || 'text'}"]`,
                        required: input.required
                    });
                });
                
                // Select dropdowns
                document.querySelectorAll('select').forEach(select => {
                    const { label, parentText } = getFieldDescription(select);
                    const options = Array.from(select.options)
                        .filter(opt => opt.value && opt.text)
                        .map(opt => ({
                            value: opt.value,
                            text: opt.text.trim(),
                            selected: opt.selected
                        }));
                    
                    formFields.push({
                        type: 'select',
                        label, parentText,
                        id: select.id || '',
                        name: select.name || '',
                        options,
                        selector: select.id ? `#${select.id}` : select.name ? `[name="${select.name}"]` : 'select',
                        required: select.required
                    });
                });
                
                // File inputs
                document.querySelectorAll('input[type="file"]').forEach(input => {
                    const { label, parentText } = getFieldDescription(input);
                    formFields.push({
                        type: 'file',
                        label, parentText,
                        id: input.id || '',
                        name: input.name || '',
                        accept: input.accept || '',
                        selector: input.id ? `#${input.id}` : input.name ? `[name="${input.name}"]` : 'input[type="file"]',
                        required: input.required
                    });
                });
                
                return formFields;
            }''')

            print("\nFound form fields:", json.dumps(form_structure, indent=2))

            # Analyze fields with GPT-4
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert at analyzing form fields.
                        Given form field information and user data, map fields appropriately:
                        1. For text/email inputs, map to corresponding user info
                        2. For dropdowns, analyze options and select the EXACT matching option value
                        3. For file inputs, indicate what type of file is needed (resume, cover letter, etc.)
                        4. If a field doesn't match user info, add it to unknown_questions
                        
                        Return a JSON object with these keys:
                        1. "field_mapping": Dictionary mapping selectors to values
                        2. "file_requirements": Dictionary mapping file input selectors to required file types
                        3. "unknown_questions": List of fields needing user input"""
                    },
                    {
                        "role": "user",
                        "content": f"""
                        User information:
                        {json.dumps(user_info, indent=2)}
                        
                        Form fields:
                        {json.dumps(form_structure, indent=2)}
                        
                        Return ONLY a JSON object with the specified keys.
                        For dropdowns, use EXACT option values from the options list.
                        """
                    }
                ]
            )

            try:
                ai_response = json.loads(response.choices[0].message.content.strip())
                field_mapping = ai_response["field_mapping"]
                file_requirements = ai_response.get("file_requirements", {})
                unknown_questions = ai_response["unknown_questions"]
                
                print("\nAI-generated field mapping:", json.dumps(field_mapping, indent=2))
                print("\nFile requirements:", json.dumps(file_requirements, indent=2))
                print("\nFields needing input:", json.dumps(unknown_questions, indent=2))

                # Fill form fields
                for selector, value in field_mapping.items():
                    try:
                        element = await page.wait_for_selector(selector, timeout=3000)
                        if not element:
                            print(f"Element not found: {selector}")
                            continue
                        
                        # Handle different input types
                        element_type = await page.evaluate("""(selector) => {
                            const el = document.querySelector(selector);
                            return el ? el.tagName.toLowerCase() : null;
                        }""", selector)
                        
                        if element_type == 'select':
                            # Get and print available options for debugging
                            options = await page.evaluate("""(selector) => {
                                const select = document.querySelector(selector);
                                return Array.from(select.options).map(o => ({
                                    value: o.value,
                                    text: o.text.trim()
                                }));
                            }""", selector)
                            print(f"\nDropdown {selector} options:", options)
                            
                            # Try exact value first, then try matching by text
                            try:
                                await element.select_option(value=value)
                                print(f"Selected option value={value} in dropdown {selector}")
                            except Exception as e:
                                print(f"Couldn't select by value, trying by text: {e}")
                                await element.select_option(label=value)
                                print(f"Selected option text={value} in dropdown {selector}")
                        else:
                            await element.fill(value)
                            print(f"Filled {selector} with {value}")
                            
                    except Exception as e:
                        print(f"Error filling {selector}: {str(e)}")

                # Handle file uploads
                for selector, file_type in file_requirements.items():
                    try:
                        file_input = await page.wait_for_selector(selector, timeout=3000)
                        if not file_input:
                            print(f"File input not found: {selector}")
                            continue
                            
                        # Get the appropriate file path based on type
                        file_path = user_info.get(f"{file_type}_path")
                        if file_path and os.path.exists(file_path):
                            await file_input.set_input_files(file_path)
                            print(f"Uploaded {file_type} from {file_path}")
                        else:
                            print(f"Missing {file_type} file at {file_path}")
                            unknown_questions.append(f"Please provide {file_type}")
                            
                    except Exception as e:
                        print(f"Error uploading file to {selector}: {str(e)}")

                print("\nForm filled. Press Enter to close browser...")
                input()
            except Exception as e:
                print(f"Error parsing OpenAI response: {e}")
                print(f"Raw response: {response.choices[0].message.content}")
        except Exception as e:
            print(f"Error during form filling: {e}")
        finally:
            await browser.close()

# Example usage
if __name__ == "__main__":
    url = "https://jobs.ashbyhq.com/haydenai/15ccdb3b-630f-40ef-8253-f6c7372f3e3e/application"
    user_info = {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "experience": "5+ years",
        "education": "Bachelor's Degree",
        "role": "Software Engineer",
        "location": "San Francisco, CA",
        "resume_path": "path/to/resume.pdf",  # Add file paths
        "cover_letter_path": "path/to/cover_letter.pdf"
    }
    
    asyncio.run(fill_and_submit_form(url, user_info))
