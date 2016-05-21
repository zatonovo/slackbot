import os
from configobj import ConfigObj, flatten_errors
from validate import Validator

CONFFILE = os.getenv('PZBOT_CONFIG')
CONFSPECFILE = os.getenv('PZBOT_CONFIG_SPEC')

class ConfigError(Exception):
  pass

def _validate(config):
  # Ensure configuration has proper data types
  validator = Validator()
  results = config.validate(validator)

  if not results:
    for (section_list, key, _) in flatten_errors(config, results):
      if key is not None:
        msg = 'The "%s" key in the section "%s" failed validation'
        print msg % (key, ', '.join(section_list))
      else:
        print 'The following section was missing:%s ' % ', '.join(section_list)
    raise ConfigError("Invalid Config syntax")





'''
If you use Slack Web API to send messages (with send_webapi() or reply_webapi()),
you can customize the bot logo by providing Icon or Emoji.
If you use Slack RTM API to send messages (with send() or reply()),
the used icon comes from bot settings and Icon or Emoji has no effect.
'''
# BOT_ICON = 'http://lorempixel.com/64/64/abstract/7/'
# BOT_EMOJI = ':godmode:'

configobj = ConfigObj(CONFFILE, unrepr=True, encoding='UTF-8')
#  configspec=CONFSPECFILE)
#_validate(configobj)

config = configobj['slackbot']

DEBUG = config['debug']
PLUGINS = config['plugins']
try:
  API_TOKEN = config['api_token']
except:
  API_TOKEN = None

HANDLERS = config['handlers'].dict()

