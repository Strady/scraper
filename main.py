import argparse
import json
import logging
import re
from random import choice, random

import requests
import time

import sys
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.exceptions import ProxyError, SSLError


import config

class Captcha(Exception):
    pass

def error_handler(func):
    def error_handler_wrapper(*args, **kwargs):
        self = args[0]
        while True:
            try:
                return func(*args, **kwargs)
            except Captcha:
                self.logger.error('Captcha! Getting new proxy')
                self.user_agent = choice(config.USER_AGENT)
                self.set_new_proxy()
            except (ProxyError, SSLError) as e:
                self.logger.error(str(e))
                self.logger.error('Not working proxy. Getting new one.')
                self.set_new_proxy()
            except Exception as e:
                self.logger.warning(str(e))
                self.set_new_proxy()
                # time.sleep(10 + 30 * random())
                continue

    return error_handler_wrapper


class API(object):
    def __init__(self):
        self.LastResponse = None
        self.LastPage = None
        self.session = requests.Session()
        self.session.mount('https://', HTTPAdapter(max_retries=1))
        from proxy_switcher import ProxySwitcher
        self.proxy_switcher = ProxySwitcher()
        self.user_agent = choice(config.USER_AGENT)
        self.session.proxies = None

        self.products = []

        # handle logging
        self.logger = logging.getLogger('[yandex-market-scraper]')
        self.logger.setLevel(logging.DEBUG)
        logging.basicConfig(format='%(asctime)s %(message)s',
                            filename='ymscraper.log',
                            level=logging.INFO)
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

        # Proxy mode on
        # self.set_new_proxy()

    @error_handler
    def send_request(self, endpoint, params=None):
        if not self.session:
            self.logger.critical("Session is not created.")
            raise Exception("Session is not created!")

        self.session.headers.update({'Connection': 'close',
                                     'Accept': '*/*',
                                     'Content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                                     'Cookie2': '$Version=1',
                                     'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.6,en;q=0.4',
                                     'User-Agent': self.user_agent})

        if 'http' not in endpoint:
            endpoint = config.BASE_URL + endpoint


        # self.logger.debug('current proxy: {}'.format(self.session.proxies))
        params = params or {}
        self.logger.debug('requesting url "{}" with params={}'.format(endpoint, params))
        response = self.session.get(endpoint, params=params, timeout=5)

        if response.status_code == 200:
            if 'showcaptcha' in response.url:
                raise Captcha
            self.LastResponse = response
            self.LastPage = response.text
            return True
        else:
            self.logger.warning("Request return " +
                                str(response.status_code) + " error!")
            if response.status_code == 429:
                sleep_minutes = 5
                self.logger.warning("That means 'too many requests'. "
                                    "I'll go to sleep for %d minutes." % sleep_minutes)
                time.sleep(sleep_minutes * 60)

            # for debugging
            try:
                self.LastResponse = response
                self.LastPage = response.text.decode('cp1251')
            except Exception as e:
                self.logger.error(str(e))
            return False


    @error_handler
    def get_page_by_name(self, name, page=1):
        """
        Загружает страницу с результатами поиска товара
        """
        if not name:
            self.logger.warning('Parameter "name" must be exist')
            return False
        return self.send_request('/search', params={'text': name})

    @error_handler
    def get_page_by_url(self, url=None, params=None):
        """
        Загружает страницу, расположенную по переданному URL
        """
        if not url:
            self.logger.warning('Parameter "url" must be exist')
            return False
        result = self.send_request(url, params=params)
        if result:
            return self.LastPage

    def set_new_proxy(self, new_proxy=None):
        """
        Устанавливает новый прокси-сервер для запросов
        """
        while not new_proxy:
            new_proxy = self.proxy_switcher.get_new_proxy()
        self.session.proxies = {'https': new_proxy}
        self.logger.info("New proxy - {0} [LEFT {1}]".format(new_proxy, len(self.proxy_switcher.proxies)))


    def get_link_for_product_by_name(self, name, page_text):
        """
        На странице с результами поиска товара
        ищет ссылку на товар
        """
        a = BeautifulSoup(page_text, 'html.parser').find(
            'a', {'title': re.compile(r'.*{}.*'.format(name), re.IGNORECASE)})

        if a is not None:
            href = a.attrs['href'].split('?')[0]
            return href

    def get_number_of_pages_in_offers(self):
        """
        Возвращает количество страниц с предложениями
        по товару
        """
        pager_div = BeautifulSoup(self.LastPage, 'html.parser').find('div', {'class': 'n-pager i-bem'})
        data_bem_str = pager_div.attrs.get('data-bem')
        data_bem_dict = json.loads(data_bem_str)
        return data_bem_dict['n-pager'].get('pagesCount')

    def get_offers_cards_from_page(self, page):
        """
        Возвращает предложения по товару
        с переданной страницы
        """
        offer_cards = BeautifulSoup(page, 'html.parser').find_all('div', {'class': 'n-snippet-card'})
        return offer_cards

    def get_price_from_offer(self, offer):
        """
        Извлекает цену товара из предложения
        """
        try:
            data = json.loads(offer.attrs.get('data-bem'))
            return data['shop-history']['clickParams']['price']
        except Exception as e:
            self.logger.error('can\'t get price from offer: {}'.format(e))

    def get_shop_from_offer(self, offer):
        """
        Извлекает название магазина из предложения
        """
        div = offer.find('div', {'class': 'b-popup-complain'})
        data = json.loads(div.attrs['data-bem'])
        shop_name = data['b-popup-complain']['shop']['name']
        return shop_name


parser = argparse.ArgumentParser(add_help=True)
parser.add_argument('product', type=str, nargs=1, help='product name')
args = parser.parse_args()

if __name__ == '__main__':
    product_name = args.product[0]
    print('ищем товар "{}"'.format(product_name))
    bot = API()

    # # ищем ссылку на страницу с товаром
    seach_result = bot.get_page_by_name(product_name)
    if seach_result:
        link = bot.get_link_for_product_by_name(product_name, bot.LastPage)
        if not link:
            bot.logger.error('товар не найден')
            sys.exit(0)
    else:
        bot.logger.error('товар не найден')
        sys.exit(0)

    # загружаем первую страницу с предложениями, смотрим сколько всего страниц
    offer_pages = []
    offers_url = link + '/offers'
    page = bot.get_page_by_url(offers_url)
    if page:
        num_of_pages = bot.get_number_of_pages_in_offers()
        bot.logger.debug('adding page 1 of {}'.format(num_of_pages))
        offer_pages.append(page)
    else:
        sys.exit(0)

    # загружаем остальные страницы с предложениями
    for i in range(2, num_of_pages + 1):
        page = bot.get_page_by_url(offers_url, params={'page': str(i)})
        if page:
            bot.logger.debug('adding page {} of {}'.format(i, num_of_pages))
            offer_pages.append(page)

    # ищем предложения на страницах
    all_offers = []
    for page in offer_pages:
        offers_from_the_page = bot.get_offers_cards_from_page(page)
        all_offers += offers_from_the_page

    bot.logger.debug('количество страниц с предложениями: {}'.format(num_of_pages))
    print('количество предложений: {}'.format(len(all_offers)))
    shops_to_prices = {}
    for offer in all_offers:
        price = bot.get_price_from_offer(offer)
        shop = bot.get_shop_from_offer(offer)
        shops_to_prices[shop] = price

    for shop, price in shops_to_prices.items():
        print('магазин "{}", цена "{}"'.format(shop, price))
