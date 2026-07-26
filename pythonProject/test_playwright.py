import pytest
from playwright.sync_api import Page, expect

BASE_URL = "https://the-internet.herokuapp.com"


def test_navigation_to_checkboxes(page: Page):
    # 1. открываем главную страницу
    page.goto(BASE_URL)
    # 2. Находим ссылку "Checkboxes"
    link = page.locator("a", has_text="Checkboxes")

    # 3. Проверяем что ссылка видна
    expect(link).to_be_visible()

    # 4. кликаем по ссылке
    link.click()

    # 5. произошёл лши переход
    expect(page).to_have_url(f"{BASE_URL}/checkboxes")

    # 6. Проверяем, что на странице есть чекбоксы
    checkboxes = page.locator("input[type='checkbox']")
    expect(checkboxes).to_have_count(2)
