import asyncio
import datetime
import decimal
import logging
import random
from dataclasses import dataclass
from enum import Enum
from html import unescape
from itertools import permutations
from pprint import pprint
from typing import Dict, Any, Optional, List, Union

import aiohttp
from aiohttp.typedefs import StrOrURL
from lxml import html

logging.basicConfig(
    level=logging.INFO,
    format=u'%(filename)s:%(lineno)d #%(levelname)-8s [%(asctime)s] - %(name)s - %(message)s',
)
logger = logging.getLogger(__name__)

@dataclass
class DEFAULTS:
    """
    Some default values for following APIs:
        1. Yahoo Finance (https://finance.yahoo.com/currencies/)
        2. Moscow Exchange (MOEX) (https://www.moex.com/ru/markets/currency/)
        3. Garantex Exchange (https://garantex.io)
        4. Trongrid (https://www.trongrid.io/) (get TRC20 account balance and last 20 transactions)
        5. Bsccan Binance Smart Chain Explorer (https://bscscan.com/)
            (get BSC-USD account balance and last 10 transactions)
        6. Web scrapping currencies rate from https://xe.com

    You must provide own api key for Trongrid and Bsccan
    """
    YAHOO_API_URL: str = 'https://query2.finance.yahoo.com/v7/finance/quote'
    YAHOO_SYMBOLS: str = 'USDRUB=X,CNYRUB=X,USDCNY=X,EURRUB=X,BTC-USD'

    MOEX_API_URL: str = 'https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities.json'
    MOEX_SYMBOLS: str = 'USD000UTSTOM,CNYRUB_TOM,EUR_RUB__TOM'
    MOEX_API_PARAMS = {"iss.meta": "off",
                       "iss.only": "securities,marketdata",
                       "securities.columns": "SECID,SHORTNAME,SECNAME",
                       "marketdata.columns": "WAPRICE,UPDATETIME,SECID,SYSTIME"}

    GARANTEX_API_URL = 'https://garantex.io/api/v2/depth'

    TRON_API_URL: str = 'https://api.trongrid.io/v1/accounts/'
    TRON_API_KEY: str = '6531dea6-b4e9-4596-8dc7-fb574c3b9d64'
    TRON_USDT_CONTRACT: str = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'

    BSCSCAN_API_URL: str = 'https://api.bscscan.com/api/'
    BSCSCAN_API_KEY: str = 'CZQE9HM9A3ENDY4JTINKB3IXCVDQQ9C7EZ'
    BSCSCAN_USDT_CONTRACT: str = '0x55d398326f99059ff775485246999027b3197955'

    XE_URL: str = 'https://www.xe.com/currencyconverter/convert/'
    XE_SYMBOLS: str = 'RUB, USD, CNY, XBT'

    USER_AGENT: str = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' \
                      'Chrome/86.0.4240.198 Safari/537.36 OPR/72.0.3815.465 (Edition Yx GX)'


class UrlReaderMode(Enum):
    HTML = 0
    JSON = 1


@dataclass
class CurrencyRate:
    symbol: str = ''
    name: str = ''
    rate: decimal.Decimal = decimal.Decimal('0')
    updated_at: datetime = datetime.datetime.now()


@dataclass
class MOEXMetadata:
    shortname: str = ''
    secname: str = ''


@dataclass
class DepthOfMarket:
    market: str
    ask_price: decimal.Decimal
    ask_factor: decimal.Decimal
    bid_price: decimal.Decimal
    bid_factor: decimal.Decimal
    updated_at: datetime = datetime.datetime.now()


class UrlReaderException(BaseException):
    pass


class UrlReader:
    """
    This is base class get JSON data or HTML page from various API.
    Fully customizable, may work in asyncio.gather for best performance.
    """

    def __init__(self,
                 session: Optional[aiohttp.ClientSession] = None,
                 url: Optional[StrOrURL] = None,
                 params: Optional[Dict] = None,
                 headers: Optional[Dict] = None,
                 mode: UrlReaderMode = UrlReaderMode.JSON,
                 logger: Optional[logging.Logger] = None,
                 **kwargs) -> None:

        self.__session = session or aiohttp.ClientSession()
        self.__url: StrOrURL = url
        self.__params = params or None
        self.__headers = headers or None
        self.__mode = mode
        self.__response_status = 0
        self.__response_url: StrOrURL = ''
        self.__logger = logger or logging.getLogger(self.__class__.__module__)
        self.__result = None

    @property
    def session(self):
        return self.__session

    @session.setter
    def session(self, session: aiohttp.ClientSession):
        self.__session = session

    @property
    def url(self) -> StrOrURL:
        return self.__url

    @url.setter
    def url(self, url: StrOrURL):
        self.__url = url

    @property
    def params(self) -> Dict:
        return self.__params

    @params.setter
    def params(self, params: Dict):
        self.__params = params

    @property
    def headers(self) -> Dict:
        return self.__headers

    @headers.setter
    def headers(self, headers: Dict):
        self.__headers = headers

    @property
    def status(self):
        return self.__response_status

    @property
    def response_url(self) -> StrOrURL:
        return self.__response_url

    @property
    def logger(self):
        return self.__logger

    async def _get_raw_data(self, url: StrOrURL = None,
                            params: Dict = None,
                            headers: Dict = None,
                            delay: float = 0,
                            task_key: str = None,
                            task_name: str = None
                            ) -> Optional[Dict[str, Any]]:
        """
        :param url: JSON API url
        :param params: params dictionary
        :param headers: headers dictionary
        :param delay: Delay for adjust API requirements requests rate limiting
        :param task_key: Mixin key in result
        :param task_name: Mixin key value in result
        :return: JSON response
        """
        url = url or self.__url
        if not url and not self.__url:
            self.__logger.error("Url can not be None.")
            raise ValueError("Url can not be None.")
        params = params or self.params
        headers = headers or self.headers
        self.__result = None
        try:
            await asyncio.sleep(delay)
            async with self.session.get(url, params=params, headers=headers) as response:
                self.__response_url = response.url
                self.__response_status = response.status
                self.__result = await response.json(encoding='utf-8') \
                    if self.__mode == UrlReaderMode.JSON else await response.text()
                if self.__result and task_key and task_key in self.__result and self.__mode == UrlReaderMode.JSON:
                    raise KeyError(f"Task key {task_key} already exist in JSON data.")
                if task_key and not task_name:
                    self.__logger.warning("Task name is None for task key %s.", task_key)
                if task_key and self.__mode == UrlReaderMode.JSON:
                    self.__result[task_key] = task_name
        except aiohttp.ClientError as err:
            self.__logger.error("Error while fetching url: %r,\nresponse is %s.", err, unescape(await response.text()))
        except Exception as err:
            self.__logger.error("Error while fetching url: %r,\nresponse is %s.", err, unescape(await response.text()))
        finally:
            return self.__result


class YahooReader(UrlReader):
    def __init__(self,
                 session: Optional[aiohttp.ClientSession] = None,
                 symbols: Union[str, List[str]] = 'RUB=X',
                 logger: Optional[logging.Logger] = None) -> None:
        super().__init__(session, DEFAULTS.YAHOO_API_URL, logger)
        if isinstance(symbols, str):
            symbols = [symbols]
        if not isinstance(symbols, list):
            raise ValueError("Symbols must be string or list of strings.")
        self.params: dict = {"symbols": ",".join(symbols)}
        self.headers: dict = {"User-Agent": DEFAULTS.USER_AGENT,
                              'Content-Type': "application/json"}
        self.source_name: str = "YAHOO"
        self.source_url: StrOrURL = "https://finance.yahoo.com/currencies/"

    async def get_rates(self) -> dict:
        """
        :return: Currencies rates
        """
        json_data = await self._get_raw_data(url=self.url,
                                             params=self.params,
                                             headers=self.headers)
        return {data['symbol']: CurrencyRate(data['symbol'],
                                             data['shortName'],
                                             decimal.Decimal(str(data['regularMarketPrice'])),
                                             datetime.datetime.now()
                                             ) for data in json_data['quoteResponse']['result'] if json_data}


class MOEXReader(UrlReader):
    def __init__(self,
                 session: Optional[aiohttp.ClientSession] = None,
                 symbols: Union[str, List[str]] = 'USD000UTSTOM',
                 logger: Optional[logging.Logger] = None) -> None:

        super().__init__(session, DEFAULTS.MOEX_API_URL, logger)
        if isinstance(symbols, list):
            symbols = ", ".join(symbols)
        if not isinstance(symbols, str):
            raise ValueError("Symbols must be string or list of strings.")
        self.symbols: str = symbols
        self.params: dict = DEFAULTS.MOEX_API_PARAMS
        self.headers: dict = {"User-Agent": DEFAULTS.USER_AGENT,
                              'Content-Type': "application/json"}
        self.source_name: str = "MOEX"
        self.source_url: StrOrURL = "https://www.moex.com/ru/markets/currency/"

        self.__moex_metadata: dict = {}

    async def get_rates(self) -> Optional[Dict[str, Any]]:
        """
        :return: Currencies rates
        """
        json_data = await self._get_raw_data(url=self.url,
                                             params=self.params,
                                             headers=self.headers)
        self.__moex_metadata = {data[0]: MOEXMetadata(data[1], data[2]) for data in json_data['securities']['data']
                                if json_data}
        return {data[2]: CurrencyRate(self.__moex_metadata[data[2]].shortname,
                                      self.__moex_metadata[data[2]].secname,
                                      decimal.Decimal(str(data[0]) or '0'),
                                      datetime.datetime.fromisoformat(data[3]))
                for data in json_data['marketdata']['data'] if json_data and (data[0] and data[2] in self.symbols)}


class GarantexReader(UrlReader):
    def __init__(self,
                 session: Optional[aiohttp.ClientSession] = None,
                 market: str = 'usdtrub',
                 logger: Optional[logging.Logger] = None) -> None:
        super().__init__(session, DEFAULTS.GARANTEX_API_URL, logger)
        if not isinstance(market, str):
            raise ValueError("Market must be string.")
        self.params: dict = {"market": market}
        self.headers: dict = {"User-Agent": DEFAULTS.USER_AGENT,
                              'Content-Type': "application/json"}
        self.source_name: str = "GARANTEX"
        self.source_url: StrOrURL = "https://garantex.io/"

    async def get_dom(self) -> Optional[DepthOfMarket]:
        """
        :return: Depth of market first row
        """
        json_data = await self._get_raw_data()
        return DepthOfMarket("USDT/РУБ",
                             decimal.Decimal(json_data['asks'][0]['price']),
                             decimal.Decimal(json_data['asks'][0]['factor']),
                             decimal.Decimal(json_data['bids'][0]['price']),
                             decimal.Decimal(json_data['bids'][0]['factor']),
                             datetime.datetime.fromtimestamp(json_data['timestamp'])
                             ) if json_data else None


class TronWalletReader(UrlReader):
    def __init__(self,
                 wallets: Union[str, List[str]],
                 usdt_contract: str = DEFAULTS.TRON_USDT_CONTRACT,
                 api_key: Optional[str] = DEFAULTS.TRON_API_KEY,
                 session: Optional[aiohttp.ClientSession] = None,
                 logger: Optional[logging.Logger] = None) -> None:
        super().__init__(session, DEFAULTS.TRON_API_URL, logger)
        self.headers = {'User-Agent': DEFAULTS.USER_AGENT,
                        'Content-Type': "application/json",
                        'Accept': "application/json"}
        if api_key:
            self.headers['TRON-PRO-API-KEY'] = api_key
        self.scale = 10 ** 6
        self.usdt_contract: str = usdt_contract
        self.__wallets: list = []
        self.urls: dict = {}
        self.trnx_urls: dict = {}
        self.wallets = wallets

    @property
    def wallets(self) -> list:
        return self.__wallets

    @wallets.setter
    def wallets(self, value: Union[str, List[str]]):
        if isinstance(value, str):
            self.__wallets = ''.join(value.split()).split(',')
        elif isinstance(value, list):
            self.__wallets = value
        else:
            raise ValueError("Wallets must be string or list of strings.")
        self.urls = {wallet: f"{self.url}{wallet}" for wallet in self.__wallets}
        self.trnx_urls = {wallet: f"{self.url}{wallet}/transactions/trc20" for wallet in self.__wallets}

    async def __fetch_urls(self, urls) -> Optional[tuple]:
        """
        :return: Raw JSON response
        """
        delay = random.uniform(0.07, 0.09)
        tasks = [asyncio.create_task(self._get_raw_data(url=url,
                                                        params=self.params,
                                                        headers=self.headers,
                                                        delay=delay * i,
                                                        task_key='wallet_address',
                                                        task_name=address))
                 for i, (address, url) in enumerate(urls.items(), start=1)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        return responses

    async def get_balances(self) -> Optional[dict]:
        """
        :return: Wallets balances
        """
        wallets = {address: 0 for address in self.__wallets}
        raw_data = await self.__fetch_urls(self.urls)
        for balance in raw_data:
            if not balance['success']:
                wallets[balance['wallet_address']] = -1
                self.logger.info("Error: %s, wallet: %s", balance['error'], balance['wallet_address'])
                continue
            trc20 = next((item for item in balance['data'] if item["trc20"]), None)
            wallets[balance['wallet_address']] = int(next((item.get(self.usdt_contract, 0) for item in trc20["trc20"]
                                                           if item.get(self.usdt_contract, None)), 0)) if trc20 else 0
        return wallets

    async def get_transactions(self) -> Optional[dict]:
        """
        :return: Last wallet transactions
        """
        wallets = {address: [] for address in self.__wallets}
        raw_data = await self.__fetch_urls(self.trnx_urls)
        for transactions in raw_data:
            if not transactions.get('success', False):
                self.logger.info("Error: %s, wallet: %s", transactions.get('error', 'Unknown error'),
                                 transactions['wallet_address'])
                continue
            for trn in transactions['data']:
                if trn['token_info']['address'] != DEFAULTS.TRON_USDT_CONTRACT or \
                        trn['token_info']['symbol'].upper() != 'USDT':
                    continue
                value = int(trn['value'])
                trn_from = trn['from']
                if trn_from == transactions['wallet_address']:
                    trn_from = trn['to']
                    value *= -1

                wallets[transactions['wallet_address']].append({'wallet': trn_from,
                                                                'timestamp': datetime.datetime.fromtimestamp(
                                                                    trn['block_timestamp'] / 1000.0,
                                                                    datetime.timezone.utc),
                                                                'value': value})
        return wallets


class BscScanWalletReader(UrlReader):
    def __init__(self,
                 wallets: Union[str, List[str]],
                 usdt_contract: str = DEFAULTS.BSCSCAN_USDT_CONTRACT,
                 api_key: Optional[str] = DEFAULTS.BSCSCAN_API_KEY,
                 session: Optional[aiohttp.ClientSession] = None,
                 logger: Optional[logging.Logger] = None) -> None:
        super().__init__(session, DEFAULTS.BSCSCAN_API_URL, logger)
        self.headers = {'User-Agent': DEFAULTS.USER_AGENT,
                        'Content-Type': "application/json",
                        'Accept': "application/json"}
        self.scale = 10 ** 12
        self.usdt_contract: str = usdt_contract
        self.api_key: str = api_key
        self.__wallets: list = []
        self.balance_params_list: list = []
        self.trnx_params_list: list = []
        self.wallets = wallets
        self.url: StrOrURL = DEFAULTS.BSCSCAN_API_URL

    @property
    def wallets(self):
        return self.__wallets

    @wallets.setter
    def wallets(self, value: Union[str, List[str]]):
        if isinstance(value, str):
            self.__wallets = ''.join(value.split()).split(',')
        elif isinstance(value, list):
            self.__wallets = value
        else:
            raise ValueError("Wallets must be string or list of strings.")
        self.balance_params_list = [{'module': 'account',
                                     'action': 'tokenbalance',
                                     'contractaddress': self.usdt_contract,
                                     'address': wallet,
                                     'tag': 'latest',
                                     'apikey': self.api_key} for wallet in self.wallets]
        self.trnx_params_list = [{'module': 'account',
                                  'action': 'tokentx',
                                  'contractaddress': DEFAULTS.BSCSCAN_USDT_CONTRACT,
                                  'address': wallet,
                                  'page': '1',
                                  'offset': '10',
                                  'startblock': '0',
                                  'endblock': '999999999',
                                  'sort': 'desc',
                                  'apikey': self.api_key} for wallet in self.wallets]

    async def __fetch_urls(self, params: list) -> Optional[tuple]:
        """
        :return: Raw JSON response
        """
        delay = random.uniform(0.01, 0.03)
        tasks = [asyncio.create_task(self._get_raw_data(self.url,
                                                        params=wallet_params,
                                                        headers=self.headers,
                                                        delay=delay * i,
                                                        task_key='wallet_address',
                                                        task_name=wallet_params['address']))
                 for i, wallet_params in enumerate(params, start=1)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        return responses

    async def get_balances(self) -> Optional[dict]:
        """
        :return: Wallets balances
        """
        wallets = {address: 0 for address in self.__wallets}
        raw_data = await self.__fetch_urls(self.balance_params_list)
        for balance in raw_data:
            if balance['message'].upper() == 'OK':
                wallets[balance['wallet_address']] = int(balance['result'])
            else:
                self.logger.info("Error: %s, wallet: %s", balance.get('message', 'Unknown error'),
                                 balance['wallet_address'])
                wallets[balance['wallet_address']] = -1
        return wallets

    async def get_transactions(self) -> Optional[dict]:
        """
        :return: Last 10 wallet transactions
        """
        wallets = {address: [] for address in self.__wallets}
        raw_data = await self.__fetch_urls(self.trnx_params_list)
        for transactions in raw_data:
            if not transactions or transactions['message'].upper() != 'OK':
                self.logger.info("Error: %s, wallet: %s", transactions.get('message', 'Unknown error'),
                                 transactions['wallet_address'])
                continue
            for trn in transactions['result']:
                if trn['tokenSymbol'] != 'BSC-USD':
                    continue
                value = int(trn['value'])
                trn_from = trn['from']
                if trn_from.upper() == transactions['wallet_address'].upper():
                    trn_from = trn['to']
                    value *= -1

                wallets[transactions['wallet_address']].append({'wallet': trn_from,
                                                                'timestamp': datetime.datetime.fromtimestamp(
                                                                    int(trn['timeStamp']),
                                                                    datetime.timezone.utc),
                                                                'value': value})
        return wallets


class HTMLReader(UrlReader):
    """
    This is base class get JSON data from various API.
    Fully customizable, may work in asyncio.gather for best performance.
    """

    def __init__(self,
                 urls: Union[str, List[str]] = None,
                 session: Optional[aiohttp.ClientSession] = None,
                 params: Optional[Dict] = None,
                 headers: Optional[Dict] = None,
                 logger: Optional[logging.Logger] = None,
                 **kwargs) -> None:
        super().__init__(session=session, params=params, headers=headers, mode=UrlReaderMode.HTML, logger=logger)
        if isinstance(urls, str):
            self.__urls = ''.join(urls.split()).split(',')
        elif isinstance(urls, list):
            self.__urls = urls
        else:
            raise ValueError("Urls must be string or list of strings.")
        self.headers = {"User-Agent": DEFAULTS.USER_AGENT}

    @property
    def urls(self):
        return self.__urls

    @urls.setter
    def urls(self, value):
        if isinstance(value, str):
            self.__urls = ''.join(value.split()).split(',')
        elif isinstance(value, list):
            self.__urls = value

    async def get_pages(self) -> Optional[tuple]:
        """
        :return: Raw HTML responses
        """
        tasks = [asyncio.create_task(self._get_raw_data(url=url,
                                                        params=self.params,
                                                        headers=self.headers)) for url in self.__urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        return responses


class XeReader(HTMLReader):
    """
    This is base class get JSON data from various API.
    Fully customizable, may work in asyncio.gather for best performance.
    """

    def __init__(self,
                 session: Optional[aiohttp.ClientSession] = None,
                 symbols: Union[str, List[str]] = 'USD/RUB',
                 logger: Optional[logging.Logger] = None) -> None:
        super().__init__(session=session, urls=[], mode=UrlReaderMode.HTML, logger=logger)
        self.__symbols = ''.join(DEFAULTS.XE_SYMBOLS.split()).split(',')
        self.__pairs = [f"{pair[0]}/{pair[1]}" for pair in permutations(self.__symbols, 2)]
        if isinstance(symbols, str):
            symbols = ''.join(symbols.split()).split(',')
        if not isinstance(symbols, list):
            raise ValueError("Symbols must be string or list of strings.")
        if not set(symbols).issubset(self.__pairs):
            raise ValueError(f"Following currency pairs not supported: "
                             f"{', '.join(set(symbols).difference(set(self.__pairs)))}")
        self.headers: dict = {"User-Agent": DEFAULTS.USER_AGENT}
        self.urls = [f"{DEFAULTS.XE_URL}?Amount=1&From={pair[4:]}&To={pair[:3]}" for pair in symbols]

    async def get_rates(self) -> Optional[Dict[str, Any]]:
        pages = await self.get_pages()
        rates = {}
        for page in pages:
            tree = html.fromstring(page)
            rate = tree.xpath('//*[@id="__next"]/div[2]/div[2]/section/'
                              'div[2]/div/main/form/div[2]/div[3]/div[1]/div[1]/p[1]//text()')
            meta_rate = rate[0].split()
            if not len(meta_rate):
                continue
            symbol = f"{meta_rate[1]}/{meta_rate[-1]}"
            rates[symbol] = CurrencyRate(symbol,
                                         symbol,
                                         decimal.Decimal(meta_rate[-2].replace(',', '')),
                                         datetime.datetime.now()
                                         )
        return rates


async def test():
    # yahoo_reader = YahooReader(symbols=DEFAULTS.YAHOO_SYMBOLS)
    # rates = await yahoo_reader.get_rates()
    # pprint(rates)
    # await yahoo_reader.session.close()
    # #
    # moex_reader = MOEXReader(symbols=['USD000UTSTOM', 'CNYRUB_TOM'])
    # rates = await moex_reader.get_rates()
    # pprint(rates)
    # await moex_reader.session.close()
    # #
    # garantex_reader = GarantexReader()
    # dom = await garantex_reader.get_dom()
    # pprint(dom)
    # await garantex_reader.session.close()
    # # 'TEnGt4WMjmVDmfDm9EC6xQXPWtMpuetobC'
    # # 'TZGRrMPEQMXyZndV1BaRy4SuCd3aTuKGBi'
    # # 'TYmxU6gD48Hf82cpBBHTHNJkhn1W6MrfML'
    # # 'TC1NPeCNwCb4bazcpHig2q3s3bFQBHUt2D'
    #
    # # tron_reader = TronWalletReader(
    # #     'TZGRrMPEQMXyZndV1BaRy4SuCd3aTuKGBi')
    #
    # pprint(balances)
    # tron_reader = TronWalletReader(['TZGRrMPEQMXyZndV1BaRy4SuCd3aTuKGBi',
    #                                 'TEnGt4WMjmVDmfDm9EC6xQXPWtMpuetobC',
    #                                 'TYmxU6gD48Hf82cpBBHTHNJkhn1W6MrfML',
    #                                 'TC1NPeCNwCb4bazcpHig2q3s3bFQBHUt2D'])
    # raw_data = await tron_reader.get_raw_data()
    # pprint(raw_data)
    #
    # balances = await tron_reader.get_balances()
    # pprint(balances)
    #
    # trnx = await tron_reader.get_transactions()
    # pprint(trnx)
    # await tron_reader.session.close()
    # bscscan_reader = BscScanWalletReader(
    #     '0xE5855278Ecf07e423BAecE3168fAD755B117E261')
    # balances = await bscscan_reader.get_balances()
    # pprint(balances)
    # trnx = await bscscan_reader.get_transactions()
    # pprint(trnx)
    # await bscscan_reader.session.close()
    # https://www.xe.com/currencyconverter/convert/?Amount=25&From=USD&To=RUB
    # ['https://czcb.com.cn/','https://www.vl.ru/dengi/']
    # ['https://czcb.com.cn/',
    #  'https://www.vl.ru/dengi/']
    from lxml import html
    xpath = {0: '//*[@id="Tagbdiv1"]/table/tbody/tr[td="USD"]/td[2]',
             1: '//*[@data-bank="577"]/td[@data-currency="USD"]'
                '//span[contains(concat(" ", normalize-space(@class), " "), " js-operation-sell ")]'
                '[contains(concat(" ", normalize-space(@class), " "), " rates-desktop__value ")]'}
    result = {0: None, 1: None}
    html_reader = HTMLReader(['https://czcb.com.cn/', 'https://www.vl.ru/dengi/'])
    pages = await html_reader.get_pages()
    for i, page in enumerate(pages):
        try:
            tree = html.fromstring(page)
            data = tree.xpath(xpath[i])
            result[i] = data[0].text.strip()
        except Exception as e:
            logger.error("Error occurred while parsing url %s, error: %r", html_reader.urls[i], e)

    pprint(result)
    await html_reader.session.close()
    xe_reader = XeReader(symbols='USD/RUB, CNY/RUB, USD/CNY, XBT/USD')
    rates = await xe_reader.get_rates()
    pprint(rates)
    await xe_reader.session.close()


if __name__ == '__main__':
    asyncio.run(test())
