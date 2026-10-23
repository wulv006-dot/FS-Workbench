"""Short-lived Order browser inside the existing bounded business executor."""
import os


def open_backend(playwright):
    import fs_order_client
    browser=playwright.chromium.launch(executable_path='/opt/google/chrome/chrome',
        headless=True,timeout=8000,args=['--no-sandbox','--disable-dev-shm-usage'],
        env=dict(os.environ,HOME='/tmp',XDG_CONFIG_HOME='/tmp/.config',XDG_CACHE_HOME='/tmp/.cache'))
    try:
        context=browser.new_context(locale='zh-CN',viewport={'width':1440,'height':900})
        fs_order_client.apply(context)
        return browser
    except BaseException:
        browser.close()
        raise


def close_backend(page):
    browser=page.context.browser
    try:
        page.close()
    finally:
        browser.close()
