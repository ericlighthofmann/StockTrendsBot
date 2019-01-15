import csv
import logging
import configparser
import re
from datetime import datetime
import requests
from dateutil.relativedelta import relativedelta
import time
import json

import praw
from tqdm import tqdm
from iexfinance.stocks import Stock
from iexfinance.stocks import get_historical_data

from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail

from stocktrendsbot.models import Company, PostRepliedTo


class Command(BaseCommand):
    help = 'Runs StockTrendsBot - a reddit bot for posting stock performance.'

    def handle(self, *args, **options):

        # test flag
        test = False

        # log config
        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

        # defining variables
        config = configparser.ConfigParser()
        config.read('data/stocktrendsbot/stocktrendsbot.ini')
        reddit_id = config.get('Reddit', 'REDDIT_ID') # stored in .ini file
        reddit_secret = config.get('Reddit', 'REDDIT_SECRET') # stored in .ini file
        reddit_user_agent = config.get('Reddit', 'REDDIT_USER_AGENT') # stored in .ini file
        reddit_password = config.get('Reddit', 'REDDIT_PASSWORD') # stored in .ini file
        reddit_username = config.get('Reddit', 'REDDIT_USERNAME') # stored in .ini file

        all_companies_in_db = Company.objects.all().values_list('symbol', flat=True)
        all_company_names_in_db = Company.objects.all().values_list('name', flat=True)

        emailed = False
        emailed_datetime = None

        # @fold
        def get_company_objects():

            '''
            get a list of publicly traded companies from this url:
            https://www.nasdaq.com/screening/company-list.aspx and load into
            the database
            '''

            logging.info('Loading companies into database...')
            with open('data/stocktrendsbot/companylist.csv', 'r') as csv_file:
                csv_reader = csv.reader(csv_file)
                for row in tqdm(csv_reader):
                    symbol = row[0]
                    if symbol in all_companies_in_db:
                        continue
                    name = row[1]
                    ipo_year = row[4]
                    sector = row[5]
                    industry = row[6]

                    Company.objects.update_or_create(
                        symbol = symbol,
                        defaults = {
                            'name': name,
                            'ipo_year': ipo_year,
                            'sector': sector,
                            'industry': industry
                        }
                    )
                for company in tqdm(Company.objects.all()):
                    if not company.name_has_been_formatted:
                        company.save()

        # @fold
        def start_stocktrendsbot(praw_object):

            class StockInfo():

                def get_current_price(self, current_company):
                    logging.info('getting info for ' + str(current_company.name) + ' (' + str(current_company.symbol) + ')')
                    stock_object = Stock(current_company.symbol.upper())
                    current_price = round(float(stock_object.get_price()),2)
                    return current_price

                def get_historical_change(self, current_company):

                    one_week_ago = datetime.now() - relativedelta(weeks=1)
                    one_month_ago = datetime.now() - relativedelta(months=1)
                    one_year_ago = datetime.now() - relativedelta(years=1)

                    def get_historical_price(time_period):
                        def format_date(date_input):
                            return datetime.strftime(date_input, '%Y-%m-%d')
                        historical_price = {}
                        while historical_price == {}:
                            historical_price = get_historical_data(current_company.symbol.upper(),
                                format_date(time_period), time_period, output_format='json'
                            )
                            if historical_price == {}:
                                time_period = time_period + relativedelta(days=1)

                        price = historical_price[format_date(time_period)]['close']
                        return price

                    weekly_price = get_historical_price(one_week_ago)
                    monthly_price = get_historical_price(one_month_ago)
                    yearly_price = get_historical_price(one_year_ago)

                    return weekly_price, monthly_price, yearly_price

                def get_change(self, current_price, historical_price):
                    change = round((current_price-historical_price) / historical_price * 100,1)
                    return change

                def get_trend_text_output(self, change, time_period):
                    def get_change_marker(change):
                        if change > 0.0:
                            change_marker = '&#x25B2; +'
                        elif change < 0.0:
                            change_marker = '&#x25BC;'
                        else:
                            change_marker = 'even at'
                        return change_marker

                    change_marker = get_change_marker(change)
                    text_output = ('Over the past ' + time_period + ', ' +
                        current_company.symbol + ' is ' + change_marker + str(change) + '%' + '\n\n'
                    )
                    return text_output

                def get_text_output(self, current_company):
                    output = ('**' + current_company.name + ' (' + current_company.symbol + ')**' +
                        '\n\n' + 'Current price: $' + str(self.current_price) +
                        '\n\n' + self.weekly_text_output +
                        self.monthly_text_output +
                        self.yearly_text_output +
                        '***' + '\n\n' + '^Beep ^Boop, ^I ^am ^a ^bot. ' +
                        '^I ^delete ^my ^comments ^if ^they ^are ^-3 ^or ^lower. ' +
                        '^Message ^[HomerG](\/u\/HomerG) ^with ^any ^suggestions, ^death ^threats, ^etc.' + '\n\n' +
                        '^To ^see ^source ^code ^and ^how ^I ^was ^made, ^click ^[here.](http:\/\/www.hofdata.com/blog/stock-trends-bot)')
                    return output

                def __init__(self, current_company):

                    self.current_price = self.get_current_price(current_company)
                    self.weekly_price, self.monthly_price, self.yearly_price = \
                        self.get_historical_change(current_company)
                    self.weekly_change = self.get_change(self.current_price, self.weekly_price)
                    self.monthly_change = self.get_change(self.current_price, self.monthly_price)
                    self.yearly_change = self.get_change(self.current_price, self.yearly_price)
                    self.weekly_text_output = self.get_trend_text_output(self.weekly_change, 'week')
                    self.monthly_text_output = self.get_trend_text_output(self.monthly_change, 'month')
                    self.yearly_text_output = self.get_trend_text_output(self.yearly_change, 'year')
                    self.text_output = self.get_text_output(current_company)

            subreddit_list = [
                'asx', 'ausstocks', 'business', 'stocks', 'investing',
                'finance', 'stockmarket', 'investmentclub', 'earningreports',
                'economy', 'technology', 'wallstreetbets'
            ]

            if test:
                subreddit_list = ['testingground4bots']

            for sr in subreddit_list:

                logging.info('Switching to ' + str(sr) + '...')
                time.sleep(5)
                for submission in praw_object.subreddit(sr).new(limit=5):
                    if submission.id not in PostRepliedTo.objects.all().values_list(
                        'submission_id', flat=True
                        ):
                        for name in Company.objects.all().values_list('name', flat=True):
                            if name.lower() in submission.title.lower().replace('\'s', '').split(' '):
                                current_company = Company.objects.filter(name=name).first()
                                stock_info = StockInfo(current_company)
                                if stock_info.weekly_price != 'N/A' or stock_info.monthly_price != 'N/A' or stock_info.yearly_price != 'N/A':
                                    try:
                                        logging.info('Replying to : ' + str(submission.title))
                                        logging.info('reddit.com' + str(submission.permalink))
                                        submission.reply(stock_info.text_output)
                                        PostRepliedTo.objects.get_or_create(
                                            submission_id = submission.id,
                                            url = 'reddit.com'+submission.permalink,
                                        )
                                    except praw.exceptions.APIException as e:
                                        if 'minutes' in str(e):
                                            time_to_wait = int(str(e).split(' minutes')[0][-1:])
                                            logging.warning('Sleeping for ' + str(time_to_wait) + ' minutes.')
                                            time.sleep(time_to_wait*60+70)
                                        elif 'seconds' in str(e):
                                            time_to_wait = int(str(e).split(' seconds')[0][-2:])
                                            logging.warning('Sleeping for ' + str(time_to_wait) + ' seconds.')
                                            time.sleep(time_to_wait+10)
                                    time.sleep(10)


            # checking for downvoted comments and deleting at <= -3
            comments = praw_object.user.me().comments.new(limit=None)
            for comment in comments:
                if comment.score <= -3:
                    logging.info('Deleting a comment at ' + str(comment.permalink))
                    comment.delete()

        get_company_objects()
        while True:
            try:
                praw_object = praw.Reddit(
                    client_id = reddit_id,
                    client_secret = reddit_secret,
                    user_agent = reddit_user_agent,
                    password = reddit_password,
                    username = reddit_username
                )
                start_stocktrendsbot(praw_object)
            except Exception as e:
                def send_me_mail(e):
                    send_mail(
                    'StockTrendsBot failed!', 'STB failed with an error message of ' + str(e),
                    'ericlighthofmann@gmail.com', ['ericlighthofmann@gmail.com']
                    )
                if str(e) != 'KeyboardInterrupt':
                    if not emailed:
                        send_me_email(e)
                        emailed = True
                        emailed_datetime = datetime.now()
                    else:
                        last_emailed = datetime.now() - emailed_datetime
                        if last_emailed.seconds / 60 / 60 > 2:
                            send_me_email(e)
