# coding: utf-8
from __future__ import division

import base64
import json
import os
import random
import re
import socket
import threading
import urllib
import uuid
from collections import OrderedDict

import requests
import six

from . import helpers
from .webtrader import WebTrader, NotLoginError

log = helpers.get_logger(__file__)

# 移除心跳线程产生的日志
debug_log = log.debug


def remove_heart_log(*args, **kwargs):
    if six.PY2:
        if threading.current_thread().name == 'MainThread':
            debug_log(*args, **kwargs)
    else:
        if threading.current_thread() == threading.main_thread():
            debug_log(*args, **kwargs)


log.debug = remove_heart_log


class PATrader(WebTrader):
    config_path = os.path.dirname(__file__) + '/config/pa.json'

    def __init__(self):
        super(PATrader, self).__init__()
        self.account_config = None
        self.s = None

        self.fund_account = None

    def read_config(self, path):
        super(PATrader, self).read_config(path)

    def login(self, throw=False):
        """实现平安的自动登录"""
        self.__go_login_page()

        verify_code = self.__handle_recognize_code()
        if not verify_code:
            return False

        is_login, result = self.__check_login_status(verify_code)
        if not is_login:
            if throw:
                raise NotLoginError(result)
            return False
        trade_info = self.__get_trade_info()
        if not trade_info:
            return False

        self.__set_trade_need_info(trade_info)

        return True

    def get_balance(self):
        """获取账户资金状况"""
        return self.request(self.config['balance'])

    def get_position(self):
        """获取持仓"""
        return self.request(self.config['position'])

    def get_current_deal(self):
        """获取当日委托列表"""
        # return self.do(self.config['current_deal'])
        # TODO 目前仅在 佣金宝子类 中实现
        log.info('目前仅在 佣金宝子类 中实现, 其余券商需要补充')

    def get_exchangebill(self, start_date, end_date):
        """
        查询指定日期内的交割单
        :param start_date: 20160211
        :param end_date: 20160211
        :return:
        """
        # TODO 目前仅在 华泰子类 中实现
        log.info('目前仅在 华泰子类 中实现, 其余券商需要补充')


    def get_entrust(self):
        """获取当日委托列表"""
        return self.request(self.config['entrust'])


    def __go_login_page(self):
        """访问登录页面获取 cookie"""
        if self.s is not None:
            self.s.get(self.config['logout_api'])
        self.s = requests.session()
        self.s.get(self.config['login_page'])

    def __handle_recognize_code(self):
        """获取并识别返回的验证码
        :return:失败返回 False 成功返回 验证码"""
        # 获取验证码
        verify_code_response = self.s.get(self.config['verify_code_api'] + "?" + str(random.random()))
        # 保存验证码
        image_path = os.path.join(os.getcwd(), 'vcode')
        with open(image_path, 'wb') as f:
            f.write(verify_code_response.content)

        verify_code = helpers.recognize_verify_code(image_path, 'pa')
        log.debug('verify code detect result: %s' % verify_code)
        os.remove(image_path)

        ht_verify_code_length = 4
        if len(verify_code) != ht_verify_code_length:
            return False
        return verify_code

    def __check_login_status(self, verify_code):
        # 设置登录所需参数
        params = dict(
                password=self.account_config['password'],
                fund_account = self.account_config['fund_account'],
                ticket=verify_code
        )
        params.update(self.config['login'])

        log.debug('login params: %s' % params)
        login_api_response = self.s.post(self.config['login_api'], params)
        if login_api_response.text.find('平安证券网上营业厅登录') != -1:
            return False, login_api_response.text
        return True, None

    def __get_trade_info(self):
        """ 请求页面获取交易所需的 uid 和 password """
	params = dict(
                self.config['info'],
                random= random.random()
        )
	result = self.request(params) 
        # 查找登录信息
        sz = re.search(r'(\d{10})', result)
        sh = re.search(r'(A\d+)', result)

        if not sh or not sz:
            return False
	trade_info = {'sh':"10|%s" % sh.group(),
                      'sz': "00|%s" % sz.group()}

        log.debug('trade info: %s' % trade_info)
        return trade_info

    def __set_trade_need_info(self, account_info):
        """设置交易所需的一些基本参数
        :param json_data:登录成功返回的json数据
        """
        self.__sh_stock_account = urllib.quote(account_info['sh'])
        log.debug('sh stock account %s' % self.__sh_stock_account)
        self.__sz_stock_account = urllib.quote(account_info['sz'])
        log.debug('sz stock account %s' % self.__sz_stock_account)

    def cancel_entrust(self, entrust_no):
        """撤单
        :param entrust_no: 委托单号"""
        cancel_params = dict(
                self.config['cancel_entrust'],
                entrust_no=entrust_no
        )
        return self.request(cancel_params)

    # TODO: 实现买入卖出的各种委托类型
    def buy(self, stock_code, price, amount=0, volume=0, entrust_prop=0):
        """买入卖出股票
        :param stock_code: 股票代码
        :param price: 买入价格
        :param amount: 买入股数
        :param volume: 买入总金额 由 volume / price 取 100 的整数， 若指定 amount 则此参数无效
        :param entrust_prop: 委托类型，暂未实现，默认为限价委托
        """
        params = dict(
                self.config['buy'],
                QTY=amount if amount else volume // price // 100 * 100
        )
        return self.__trade(stock_code, price, entrust_prop=entrust_prop, other=params)

    def sell(self, stock_code, price, amount=0, volume=0, entrust_prop=0):
        """卖出股票
        :param stock_code: 股票代码
        :param price: 卖出价格
        :param amount: 卖出股数
        :param volume: 卖出总金额 由 volume / price 取整， 若指定 amount 则此参数无效
        :param entrust_prop: 委托类型，暂未实现，默认为限价委托
        """
        params = dict(
                self.config['sell'],
                QTY=amount if amount else volume // price
        )
        return self.__trade(stock_code, price, entrust_prop=entrust_prop, other=params)

    def __trade(self, stock_code, price, entrust_prop, other):
        need_info = self.__get_trade_need_info(stock_code)
        return self.request(dict(
                other,
                ACCOUT=need_info['stock_account'],  # '沪深帐号'
                SECU_CODE='{:0>6}'.format(stock_code),  # 股票代码, 右对齐宽为6左侧填充0
                PRICE=price
        ))


    def __get_trade_need_info(self, stock_code):
        """获取股票对应的证券市场和帐号"""
        # 获取股票对应的证券帐号
        stock_account = self.__sh_stock_account if helpers.get_stock_type(stock_code) == 'sh' \
            else self.__sz_stock_account

        return dict(
                stock_account=stock_account
        )

    def check_login_status(self, content):
        return True
 
    def request(self, params, auto_login=True):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko'
        }
        log.debug('request params: %s' % params)
        try:
            r = self.s.get('{prefix}'.format(prefix=self.trade_prefix), params=params, headers=headers)
            self.check_login_status(r.content)
        except NotLoginError:
            if auto_login:
                self.autologin()
                return self.request(params, False)
            else:
                raise
        return r.content

    @property
    def exchangebill(self):
        start_date, end_date = helpers.get_30_date()
        return self.get_exchangebill(start_date, end_date)

    def get_exchangebill(self, start_date, end_date):
        """
        查询指定日期内的交割单
        :param start_date: 20160211
        :param end_date: 20160211
        :return:
        """
        params = self.config['exchangebill'].copy()
        params.update({
            "start_date": start_date,
            "end_date": end_date,
        })
        return self.request(params)
