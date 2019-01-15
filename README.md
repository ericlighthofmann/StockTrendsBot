# StockTrendsBot

StockTrendsBot is a Reddit bot that is designed to listen to mentions of public companies and post a comment with the company's current price and its historical performance. Uses the IEX API to get stock prices. Here's the bot itself:

https://www.reddit.com/user/StockTrendsBot_v2

# Install
  - This program is currently designed as a Django management command. To add to your Django project:
```sh
$ python manage.py startapp stocktrendsbot
$ pip install python-dateutil, praw, tqdm, iexfinance
```
  - add a file in your data folder called "stocktrendsbot.ini" and fill in your Reddit app info (go to your Reddit user and click "apps" at the top to create a new application)
  - add the following to models.py in your new stocktrendsbot app:
```sh
import string
import re

from django.db import models

class Company(models.Model):

    symbol = models.CharField(max_length=10)
    name = models.CharField(max_length=255)
    ipo_year = models.CharField(max_length=10)
    sector = models.CharField(max_length=55)
    industry = models.CharField(max_length=55)

    name_has_been_formatted = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # remove punctuation from the name and replace suffixes
        name_formatted = re.sub(r'[^\w\s]','', self.name)
        three_char_suffix_list = ['Inc', 'Ltd', 'PLC', 'Corp']
        for suffix in three_char_suffix_list:
            if name_formatted[-3:] == suffix:
                name_formatted = name_formatted[:-3]
        two_char_suffix_list = ['Co', 'LP']
        for suffix in two_char_suffix_list:
            if name_formatted[-2:] == suffix:
                name_formatted = name_formatted[:-2]
        setattr(self, 'name', name_formatted.strip())
        setattr(self, 'name_has_been_formatted', True)
        super(Company, self).save(*args, **kwargs)

class PostRepliedTo(models.Model):

    submission_id = models.CharField(max_length=55)
    url = models.URLField(max_length=200)

    def __str__(self):
        return self.submission_id

```
  - then run the following commands:
```sh
$ python manage.py makemigrations
$ python manage.py migrate
$ python manage.py run_stocktrendsbot
```

# TODO

  - Request the page or news article that is being posted and do a topic analysis using natural language processing to determine if the poster is actually talking about a public company.

