import time

from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By

driver = Chrome()
driver.implicitly_wait(10)
driver.get("https://pytest-docs-ru.readthedocs.io/ru/latest/getting-started.html#getstarted")
u = driver.find_element(By.XPATH, "//a[@href='https://media.readthedocs.org/pdf/pytest/latest/pytest.pdf']")

u.click()

time.sleep(6)

print(u)
