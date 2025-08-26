import time
import requests
import urllib.parse
import json
import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import re
import logging
from config import Config
from database import Database
from discord_notifier import DiscordNotifier

logger = logging.getLogger(__name__)

class CarousellScraper:
    def __init__(self):
        self.db = Database()
        self.notifier = DiscordNotifier()
        self.driver = None

    def create_driver(self, headless=True):
        """Initializes and returns a Chrome WebDriver instance with maximum stealth."""
        opts = Options()
        
        # Enhanced stability and performance options
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-web-security")
        opts.add_argument("--disable-features=VizDisplayCompositor")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--ignore-ssl-errors")
        opts.add_argument("--ignore-certificate-errors-spki-list")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-backgrounding-occluded-windows")
        opts.add_argument("--disable-renderer-backgrounding")
        
        # Maximum stealth anti-detection
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
        opts.add_experimental_option('useAutomationExtension', False)
        opts.add_argument("--lang=en-US,en;q=0.9")
        
        # Rotate user agents to appear more human
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ]
        import random
        user_agent = random.choice(user_agents)
        opts.add_argument(f"--user-agent={user_agent}")
        
        if headless:
            opts.add_argument("--headless=new")

        try:
            driver = webdriver.Chrome(options=opts)
            
            # Execute comprehensive stealth scripts
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": user_agent,
                "acceptLanguage": "en-US,en;q=0.9",
                "platform": "Win32"
            })
            
            # Remove all automation indicators
            stealth_scripts = [
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
                "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})",
                "Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})",
                "Object.defineProperty(navigator, 'permissions', {get: () => ({query: () => Promise.resolve({state: 'granted'})})})",
                "Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 4})",
                "Object.defineProperty(navigator, 'deviceMemory', {get: () => 8})",
                "window.chrome = {runtime: {}}",
                "Object.defineProperty(navigator, 'connection', {get: () => ({effectiveType: '4g', rtt: 100, downlink: 10})})"
            ]
            
            for script in stealth_scripts:
                try:
                    driver.execute_script(script)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Failed to create Chrome driver: {e}")
            raise

        return driver

    def scrape_current_page(self, driver):
        """Scrapes listing information from the current page."""
        listings_data = []
        # Wait for listing cards to be present
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@data-testid, 'listing-card-')]"))
            )
        except TimeoutException:
            logger.warning("No listing cards found on the page.")
            return listings_data

        item_divs = driver.find_elements(By.XPATH, "//div[contains(@data-testid, 'listing-card-')]")
        logger.info(f"Found {len(item_divs)} item divs.")

        for i, item_div in enumerate(item_divs):
            item = Config.DEFAULT_ITEM_SCHEMA.copy()

            # Extract Product ID first from data-testid, then fallback to link regex
            try:
                product_id_from_testid = item_div.get_attribute('data-testid')
                if product_id_from_testid and product_id_from_testid.startswith('listing-card-'):
                    item['product_id'] = product_id_from_testid.replace('listing-card-', '')
            except Exception as e:
                logger.warning(f"Could not extract product_id from data-testid for item {i+1}: {e}")

            # Extract Link and potentially product_id from link
            product_link_element = None
            try:
                product_link_element = item_div.find_element(By.XPATH, ".//a[contains(@href, '/p/') and contains(@class, 'D_ls')]")
                full_link = product_link_element.get_attribute('href')

                # Normalize the link by removing query parameters
                parsed_url = urllib.parse.urlparse(full_link)
                item['link'] = urllib.parse.urlunparse(parsed_url._replace(query='', fragment=''))

                # Fallback for product_id if not found in data-testid
                if item['product_id'] is None:
                    product_id_match = re.search(r"/p/[^/]+-(\d+)", parsed_url.path)
                    item['product_id'] = product_id_match.group(1) if product_id_match else None
            except NoSuchElementException:
                logger.warning(f"Product link element not found for item {i+1}")
            except Exception as e:
                logger.warning(f"Error extracting link or product_id from link for item {i+1}: {e}")

            if item['product_id'] is None:
                logger.warning(f"Could not extract a unique product_id for item {i+1}. Skipping item.")
                continue

            # Extract Title from image alt attribute (more reliable)
            try:
                img_element = item_div.find_element(By.XPATH, ".//img[contains(@class, 'D_mm')]")
                item['img'] = img_element.get_attribute('src')

                title_from_img_alt = img_element.get_attribute('alt')
                if title_from_img_alt:
                    item['title'] = title_from_img_alt.strip()
                else:
                    # Fallback to text within a specific <p> tag if alt is not available or empty
                    if product_link_element:
                        try:
                            title_element = product_link_element.find_element(By.XPATH, ".//p[contains(@class, 'D_lI')]")
                            item['title'] = title_element.text.strip()
                        except NoSuchElementException:
                            pass
            except NoSuchElementException:
                logger.warning(f"Title or image element not found for item {i+1} (ID: {item['product_id']})")
            except Exception as e:
                logger.warning(f"Error extracting title or image for item {i+1} (ID: {item['product_id']}): {e}")
            
            # Extract Price (robust against class name changes)
            try:
                if product_link_element:
                    # Prefer price from @title attribute under product link
                    try:
                        price_element = product_link_element.find_element(By.XPATH, ".//p[@title]")
                        price_title = price_element.get_attribute('title') or ''
                        if price_title.strip():
                            item['price'] = price_title.strip()
                        else:
                            item['price'] = price_element.text.strip()
                    except NoSuchElementException:
                        # Fallback: any p that looks like a price (e.g., starts with RM)
                        price_element = product_link_element.find_element(By.XPATH, ".//p[starts-with(normalize-space(text()), 'RM') or contains(normalize-space(text()), 'RM')]")
                        item['price'] = price_element.text.strip()
            except NoSuchElementException:
                logger.warning(f"Price element not found for item {i+1} (ID: {item['product_id']})")
            except Exception as e:
                logger.warning(f"Error extracting price for item {i+1} (ID: {item['product_id']}): {e}")
                
            # Extract Seller Name and Seller URL
            try:
                seller_profile_link_element = item_div.find_element(By.XPATH, ".//a[contains(@href, '/u/') and contains(@class, 'D_ls')]")
                # Normalize seller_url by removing query parameters
                raw_seller_url = seller_profile_link_element.get_attribute('href')
                parsed_seller_url = urllib.parse.urlparse(raw_seller_url)
                item['seller_url'] = urllib.parse.urlunparse(parsed_seller_url._replace(query='', fragment=''))

                seller_name_element = seller_profile_link_element.find_element(By.XPATH, ".//p[@data-testid=\"listing-card-text-seller-name\"]")
                item['seller_name'] = seller_name_element.text.strip()
            except NoSuchElementException:
                logger.warning(f"Seller profile elements not found for item {i+1} (ID: {item['product_id']})")
            except Exception as e:
                logger.warning(f"Error extracting seller info for item {i+1} (ID: {item['product_id']}): {e}")

            # Extract Time Posted (robust paths)
            try:
                # Within seller anchor, inside D_rw -> D_aLG -> p
                time_posted_element = item_div.find_element(By.XPATH, ".//a[contains(@href, '/u/')]/div[contains(@class,'D_rw')]//div[contains(@class,'D_aLG')]//p")
                item['time_posted'] = time_posted_element.text.strip()
            except NoSuchElementException:
                try:
                    # Fallback: any p with relative time phrasing
                    time_posted_element = item_div.find_element(By.XPATH, ".//p[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'ago') or contains(text(),'seconds') or contains(text(),'minutes') or contains(text(),'hours') or contains(text(),'days')]")
                    item['time_posted'] = time_posted_element.text.strip()
                except NoSuchElementException:
                    logger.warning(f"Time posted element not found for item {i+1} (ID: {item['product_id']})")
                except Exception as e:
                    logger.warning(f"Error extracting time posted (fallback) for item {i+1} (ID: {item['product_id']}): {e}")
            except Exception as e:
                logger.warning(f"Error extracting time posted for item {i+1} (ID: {item['product_id']}): {e}")

            # Extract Condition and Size (using a more robust approach)
            try:
                # First, try to find explicit 'Condition:' or 'Size:'
                explicit_details = item_div.find_elements(By.XPATH, ".//p[contains(@class, 'D_lz') and (contains(text(), 'Condition:') or contains(text(), 'Size:'))]")
                for detail_p in explicit_details:
                    text = detail_p.text.strip()
                    if "Condition:" in text:
                        item['condition'] = text.replace("Condition:", "").strip()
                    elif "Size:" in text:
                        item['size'] = text.replace("Size:", "").strip()
                
                # If condition is still None, look for descriptive conditions in other D_lz p tags
                if item['condition'] is None:
                    descriptive_details = item_div.find_elements(By.XPATH, ".//p[contains(@class, 'D_lz') and not(contains(text(), 'Condition:')) and not(contains(text(), 'Size:'))]")
                    for detail_p in descriptive_details:
                        text = detail_p.text.strip()
                        if text in ["Lightly used", "Well used", "Like new", "Brand new", "Used"]:
                            item['condition'] = text
                            break

            except NoSuchElementException:
                logger.warning(f"Condition or Size elements not found for item {i+1} (ID: {item['product_id']})")
            except Exception as e:
                logger.warning(f"Error extracting condition or size (detail elements) for item {i+1} (ID: {item['product_id']}): {e}")
            
            # If size wasn't found in the styled p tag or explicitly, try to find it from its specific XPath if it exists
            if item['size'] is None and product_link_element:
                try:
                    size_element = product_link_element.find_element(By.XPATH, ".//p[contains(text(),'Size: ')]")
                    item['size'] = size_element.text.strip().replace("Size: ", "")
                except NoSuchElementException:
                    pass
                except Exception as e:
                    logger.warning(f"Error extracting size (fallback) for item {i+1} (ID: {item['product_id']}): {e}")
                    
            # Extract Number of Likes
            try:
                # XPath for the span containing the number of likes within the like button
                num_likes_element = item_div.find_element(By.XPATH, ".//button[@data-testid=\"listing-card-btn-like\"]/span[contains(@class, 'D_lz')] | .//button[@data-testid=\"listing-card-btn-like\"]/span[text()!='']")
                item['likes'] = num_likes_element.text.strip() if num_likes_element.text.strip() else "0"
            except NoSuchElementException:
                item['likes'] = "0"
            except Exception as e:
                logger.warning(f"Error extracting number of likes for item {i+1} (ID: {item['product_id']}): {e}")
                
            listings_data.append(item)
        return listings_data

    def go_to_next_page(self, driver):
        """Clicks the 'Show more results' button if it exists."""
        try:
            show_more_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Show more results')]"))
            )
            logger.info(f"--- Show More Results Button OuterHTML ---\n{show_more_button.get_attribute('outerHTML')}\n---")
            # Scroll to the button to ensure it's in view and clickable, centered
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", show_more_button)
            time.sleep(2)
            show_more_button.click()
            time.sleep(7)
            logger.info("Clicked 'Show more results' button.")
            return True
        except TimeoutException:
            logger.info("No more 'Show more results' button found.")
            return False
        except WebDriverException as e:
            logger.error(f"WebDriver error clicking 'Show more results': {e}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred while trying to click 'Show more results': {e}")
            return False

    def scrape_nike_shoes(self):
        """Main scraping function - tries both approaches."""
        logger.info("Starting Nike shoes scraping...")
        
        # First try direct API approach (faster, less detectable)
        try:
            listings = self.scrape_with_direct_requests()
            if listings:
                return self.process_listings(listings)
        except Exception as e:
            logger.warning(f"Direct API approach failed: {e}")
        
        # Fallback to browser approach if API fails
        try:
            listings = self.scrape_with_browser()
            if listings:
                return self.process_listings(listings)
        except Exception as e:
            logger.error(f"Browser approach also failed: {e}")
        
        # Test Discord notification system with a sample product
        # (This helps verify the system works when real products are found)
        logger.info("Testing Discord notification system...")
        test_product = {
            'product_id': 'test_nike_' + str(int(time.time())),
            'title': 'Nike Air Force 1 Low - TEST LISTING',
            'price': 'RM 120',
            'link': 'https://www.carousell.com.my/p/test-nike-shoes-12345',
            'img': 'https://via.placeholder.com/300x300?text=Nike+Test',
            'seller_name': 'Test Seller',
            'time_posted': 'Just now',
            'condition': 'New',
            'size': 'US 9'
        }
        
        # Only send test notification every 10 scrape attempts to avoid spam
        import random
        if random.randint(1, 10) == 1:
            logger.info("Sending test Discord notification...")
            success = self.notifier.send_new_listing_notification(test_product)
            if success:
                logger.info("✓ Discord notification system working correctly!")
            else:
                logger.error("✗ Discord notification system has issues")
        
        return False

    def scrape_with_direct_requests(self):
        """Try to scrape using direct HTTP requests mimicking mobile app."""
        logger.info("Trying direct API approach...")
        
        # Mobile app headers that are less likely to be blocked
        headers = {
            'User-Agent': 'Carousell/6.62.0 (iPhone; iOS 17.1.1; Scale/3.00)',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://www.carousell.com.my/',
        }
        
        session = requests.Session()
        session.headers.update(headers)
        
        # Try different API endpoints that mobile apps might use
        api_endpoints = [
            'https://www.carousell.com.my/api-service/web/listings/search/',
            'https://www.carousell.com.my/api/listings/search/',
            'https://api.carousell.com.my/v1/search/',
            'https://www.carousell.com.my/_next/data/search.json',
        ]
        
        search_params = {
            'query': 'nike shoes',
            'locale': 'en-MY',
            'country_code': 'MY',
            'limit': 20,
            'offset': 0,
            'sort_by': 'recent'
        }
        
        for endpoint in api_endpoints:
            try:
                logger.info(f"Trying API endpoint: {endpoint}")
                
                # Try both GET and POST requests
                for method in ['GET', 'POST']:
                    try:
                        if method == 'GET':
                            response = session.get(endpoint, params=search_params, timeout=10)
                        else:
                            response = session.post(endpoint, json=search_params, timeout=10)
                        
                        logger.info(f"{method} {endpoint} - Status: {response.status_code}")
                        
                        if response.status_code == 200:
                            try:
                                data = response.json()
                                logger.info(f"Got JSON response with keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
                                
                                # Look for listing data in various possible structures
                                listings = self.extract_from_api_response(data)
                                if listings:
                                    logger.info(f"Successfully extracted {len(listings)} listings from API")
                                    return listings
                                    
                            except json.JSONDecodeError:
                                # Sometimes API returns HTML, try to parse it
                                if 'nike' in response.text.lower() and 'rm' in response.text.lower():
                                    logger.info("Got HTML response, attempting to parse...")
                                    listings = self.extract_from_html_response(response.text)
                                    if listings:
                                        return listings
                                        
                    except Exception as e:
                        logger.debug(f"{method} {endpoint} failed: {e}")
                        continue
                        
            except Exception as e:
                logger.debug(f"API endpoint {endpoint} failed: {e}")
                continue
        
        logger.warning("All API endpoints failed")
        return []

    def extract_from_api_response(self, data):
        """Extract product listings from API JSON response."""
        listings = []
        
        # Common JSON structures for product listings
        possible_paths = [
            ['data', 'listings'],
            ['listings'],
            ['results'],
            ['data', 'results'],
            ['items'],
            ['data', 'items'],
            ['products'],
            ['data']
        ]
        
        for path in possible_paths:
            current = data
            try:
                for key in path:
                    current = current[key]
                
                if isinstance(current, list):
                    for item in current:
                        if isinstance(item, dict):
                            extracted = self.extract_product_from_json(item)
                            if extracted:
                                listings.append(extracted)
                                
            except (KeyError, TypeError):
                continue
        
        return listings

    def extract_product_from_json(self, item):
        """Extract product info from a JSON item."""
        try:
            product = Config.DEFAULT_ITEM_SCHEMA.copy()
            
            # Extract ID
            for id_field in ['id', 'listing_id', 'product_id', '_id', 'uuid']:
                if id_field in item:
                    product['product_id'] = str(item[id_field])
                    break
            
            # Extract title
            for title_field in ['title', 'name', 'listing_title', 'product_name']:
                if title_field in item and item[title_field]:
                    product['title'] = str(item[title_field])
                    break
            
            # Extract price
            for price_field in ['price', 'listing_price', 'amount']:
                if price_field in item:
                    price_val = item[price_field]
                    if isinstance(price_val, dict) and 'amount' in price_val:
                        product['price'] = f"RM {price_val['amount']}"
                    elif price_val:
                        product['price'] = f"RM {price_val}"
                    break
            
            # Extract image
            for img_field in ['image', 'images', 'photo', 'photos', 'thumbnail']:
                if img_field in item:
                    img_val = item[img_field]
                    if isinstance(img_val, list) and img_val:
                        product['img'] = img_val[0] if isinstance(img_val[0], str) else img_val[0].get('url', '')
                    elif isinstance(img_val, str):
                        product['img'] = img_val
                    elif isinstance(img_val, dict) and 'url' in img_val:
                        product['img'] = img_val['url']
                    break
            
            # Extract link
            if product['product_id']:
                product['link'] = f"https://www.carousell.com.my/p/{product['product_id']}"
            
            # Only return if we have essential info and it's Nike related
            if (product['product_id'] and product['title'] and 
                'nike' in product['title'].lower()):
                return product
                
        except Exception as e:
            logger.debug(f"Error extracting product from JSON: {e}")
            
        return None

    def extract_from_html_response(self, html_content):
        """Try to extract products from HTML response."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Look for JSON data embedded in script tags
            scripts = soup.find_all('script', type='application/json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    listings = self.extract_from_api_response(data)
                    if listings:
                        return listings
                except:
                    continue
            
            # Look for regular script tags with window.__DATA__ or similar
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and ('listings' in script.string or 'products' in script.string):
                    try:
                        # Try to extract JSON from JavaScript
                        import re
                        json_match = re.search(r'({.*"listings".*})', script.string)
                        if json_match:
                            data = json.loads(json_match.group(1))
                            listings = self.extract_from_api_response(data)
                            if listings:
                                return listings
                    except:
                        continue
        
        except Exception as e:
            logger.debug(f"HTML parsing failed: {e}")
        
        return []

    def scrape_with_browser(self):
        """Fallback browser-based scraping."""
        logger.info("Falling back to browser approach...")
        
        try:
            self.driver = self.create_driver(headless=True)
            
            logger.info("Establishing browser session...")
            self.driver.get("https://www.carousell.com.my/")
            time.sleep(3)
            
            logger.info(f"Navigating to: {Config.SEARCH_URL}")
            self.driver.get(Config.SEARCH_URL)
            
            max_wait = 30
            waited = 0
            
            while waited < max_wait:
                time.sleep(2)
                waited += 2
                
                current_title = self.driver.title
                logger.info(f"Wait {waited}s - Title: {current_title}")
                
                if "Just a moment" not in current_title and "Cloudflare" not in current_title:
                    logger.info("Page loaded successfully!")
                    break
            
            if "Just a moment" in self.driver.title:
                return self.try_alternative_approach()
            
            # Try to scrape
            all_listings = self.scrape_current_page(self.driver)
            
            if not all_listings:
                all_listings = self.scrape_with_alternative_selectors()
            
            return all_listings

        except Exception as e:
            logger.error(f"Browser scraping failed: {e}")
            return []
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None

    def scrape_with_alternative_selectors(self):
        """Try alternative selectors to find product listings."""
        listings_data = []
        
        # Try different selectors that might work
        alternative_selectors = [
            "//a[contains(@href, '/p/')]",  # Any link to product page
            "//div[contains(@class, 'listing')]",  # Generic listing class
            "//*[contains(@data-testid, 'listing')]",  # Any listing testid
            "//*[contains(@data-testid, 'card')]",  # Any card testid
            "//div[contains(@class, 'card')]",  # Generic card class
            "//article",  # Article tags often contain listings
            "//*[contains(text(), 'RM')]//ancestor::*[3]"  # Find elements containing prices
        ]
        
        for selector in alternative_selectors:
            try:
                elements = self.driver.find_elements(By.XPATH, selector)
                logger.info(f"Selector '{selector}' found {len(elements)} elements")
                
                if elements:
                    # Process first few elements to see if they're product listings
                    for i, element in enumerate(elements[:5]):
                        try:
                            # Look for product indicators
                            element_text = element.text[:100] if element.text else ""
                            element_html = element.get_attribute('outerHTML')[:200]
                            
                            if any(keyword in element_text.lower() for keyword in ['nike', 'rm', 'shoe']):
                                logger.info(f"Found potential product element {i}: {element_text}")
                                # Try to extract basic info
                                item = self.extract_basic_info(element)
                                if item and item.get('product_id'):
                                    listings_data.append(item)
                                    
                        except Exception as e:
                            logger.debug(f"Error processing element {i}: {e}")
                            continue
                    
                    if listings_data:
                        logger.info(f"Successfully extracted {len(listings_data)} listings with selector: {selector}")
                        break
                        
            except Exception as e:
                logger.debug(f"Error with selector {selector}: {e}")
                continue
        
        return listings_data
    
    def extract_basic_info(self, element):
        """Extract basic product info from any element."""
        item = Config.DEFAULT_ITEM_SCHEMA.copy()
        
        try:
            # Try to find link
            link_elem = element.find_element(By.XPATH, ".//a[contains(@href, '/p/')]")
            href = link_elem.get_attribute('href')
            if href:
                item['link'] = href
                # Extract product ID from URL
                product_id_match = re.search(r'/p/[^/]+-(\d+)', href)
                if product_id_match:
                    item['product_id'] = product_id_match.group(1)
                else:
                    item['product_id'] = str(hash(href))[-8:]
        except:
            pass
            
        # Try to find title
        try:
            title_elem = element.find_element(By.XPATH, ".//img[@alt]")
            item['title'] = title_elem.get_attribute('alt')
        except:
            try:
                title_elem = element.find_element(By.XPATH, ".//*[contains(text(), 'Nike') or contains(text(), 'nike')]")
                item['title'] = title_elem.text.strip()
            except:
                pass
        
        # Try to find price
        try:
            price_elem = element.find_element(By.XPATH, ".//*[contains(text(), 'RM')]")
            item['price'] = price_elem.text.strip()
        except:
            pass
            
        # Try to find image
        try:
            img_elem = element.find_element(By.XPATH, ".//img[@src]")
            item['img'] = img_elem.get_attribute('src')
        except:
            pass
        
        return item if item.get('product_id') else None
    
    def debug_find_elements(self):
        """Debug function to see what elements are actually on the page."""
        try:
            # Look for common elements that might indicate the page structure
            debug_selectors = [
                ("All links", "//a[@href]"),
                ("All images", "//img"),
                ("Elements with 'card'", "//*[contains(@class, 'card') or contains(@data-testid, 'card')]"),
                ("Elements with 'listing'", "//*[contains(@class, 'listing') or contains(@data-testid, 'listing')]"),
                ("Elements containing 'Nike'", "//*[contains(text(), 'Nike') or contains(text(), 'nike')]"),
                ("Elements containing 'RM'", "//*[contains(text(), 'RM')]"),
                ("All buttons", "//button"),
                ("All divs with data-testid", "//div[@data-testid]")
            ]
            
            for desc, selector in debug_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    logger.info(f"{desc}: Found {len(elements)} elements")
                    
                    # Log first few elements for debugging
                    for i, elem in enumerate(elements[:3]):
                        try:
                            text = elem.text[:50] if elem.text else ""
                            attrs = elem.get_attribute('class') or elem.get_attribute('data-testid') or ""
                            logger.info(f"  {i+1}. Text: '{text}' | Attrs: '{attrs}'")
                        except:
                            pass
                            
                except Exception as e:
                    logger.debug(f"Error with {desc}: {e}")
                    
        except Exception as e:
            logger.error(f"Debug function error: {e}")

    def try_alternative_approach(self):
        """Try alternative scraping approaches when main method fails."""
        logger.info("Trying alternative scraping approaches...")
        
        # Approach 1: Try different URL formats
        alternative_urls = [
            "https://carousell.com.my/search/nike%20shoes",
            "https://www.carousell.com.my/search/nike",
            "https://carousell.com.my/search/nike",
            "https://www.carousell.com.my/c/18/?query=nike%20shoes"
        ]
        
        for url in alternative_urls:
            try:
                logger.info(f"Trying alternative URL: {url}")
                self.driver.get(url)
                time.sleep(5)
                
                if "Just a moment" not in self.driver.title:
                    logger.info(f"Success with alternative URL: {url}")
                    listings = self.scrape_current_page(self.driver)
                    if listings:
                        return self.process_listings(listings)
                        
            except Exception as e:
                logger.debug(f"Alternative URL {url} failed: {e}")
                continue
        
        # Approach 2: Try mobile version
        try:
            logger.info("Trying mobile version...")
            mobile_url = "https://m.carousell.com.my/search/nike%20shoes"
            self.driver.get(mobile_url)
            time.sleep(5)
            
            if "Just a moment" not in self.driver.title:
                logger.info("Success with mobile version")
                listings = self.scrape_current_page(self.driver)
                if listings:
                    return self.process_listings(listings)
                    
        except Exception as e:
            logger.debug(f"Mobile version failed: {e}")
        
        logger.warning("All alternative approaches failed")
        return False
    
    def process_listings(self, all_listings):
        """Process found listings and send notifications."""
        if not all_listings:
            logger.warning("No listings found")
            return False

        new_listings = []
        
        for listing in all_listings:
            if listing.get('product_id') and not self.db.product_exists(listing['product_id']):
                # New product found
                self.db.save_product(listing)
                new_listings.append(listing)
                logger.info(f"New product found: {listing['title']} - {listing['price']}")

        # Send Discord notifications for new listings
        if new_listings:
            for listing in new_listings:
                success = self.notifier.send_new_listing_notification(listing)
                if success:
                    logger.info(f"Discord notification sent for: {listing['title']}")
                else:
                    logger.error(f"Failed to send Discord notification for: {listing['title']}")
            
            logger.info(f"Sent notifications for {len(new_listings)} new listings")
        else:
            logger.info("No new listings found")
        
        return len(new_listings) > 0

    def cleanup(self):
        """Cleanup resources"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None