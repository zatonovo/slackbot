# -*- coding: utf-8 -*-

import logging
import re
import time
import importlib
import threading
import slacker

import settings
from slackbot.utils import to_utf8, WorkerPool

logger = logging.getLogger(__name__)

AT_MESSAGE_MATCHER = re.compile(r'^\<@(\w+)\>:? (.*)$')


def from_bot(msg):
  return 'bot_id' in msg and msg['bot_id'] is not None


class MessageDispatcher(object):
    def __init__(self, slackclient, plugins):
        self._client = slackclient
        self._pool = WorkerPool(self.dispatch_msg)
        self._plugins = plugins
        self._stop = threading.Event()

    def start(self):
        self._pool.start()

    def dispatch_msg(self, msg):
        category = msg[0]
        msg = msg[1]
        text = self.get_text(msg)
        logger.info("Trying plugins on message %s" % text)
        responded = False
        for func, args in self._plugins.get_plugins(category, text):
            if func:
                responded = True
                try:
                    func(Message(self._client, msg), *args)
                except:
                    err = 'Failed to handle message %s with plugin "%s"'
                    logger.exception(err, text, func.__name__)
                    #logger.exception('\n%s\n' % traceback.format_exc())
                    reply = 'YIPE! "%s" failed to handle "%s"\n' % (func.__name__, text)
                    #reply += '```\n%s\n```' % traceback.format_exc()
                    self._client.rtm_send_message(msg['channel'], reply)

        if not responded and category == 'respond_to':
            self._default_reply(msg)

    def _on_new_message(self, msg):
        """
        Handle a new message and dispatch to the appropriate pool.
        If the message came from a bot, use the appropriate service handler.
        """
        logger.info("Received message: %s"%msg)
        # ignore edits
        ignore = [ 'message_changed', 'channel_join', 'message_deleted' ]
        subtype = msg.get('subtype', '')
        if subtype in ignore: return

        botname = self._client.login_data['self']['name']
        if self.get_username(msg) == botname: return

        if from_bot(msg): return self._on_bot_message(msg)

        msg_respond_to = self.filter_text(msg)
        if msg_respond_to:
            self._pool.add_task(('respond_to', msg_respond_to))
        else:
            self._pool.add_task(('listen_to', msg))

    def _on_bot_message(self, msg):
      """
      Check bot handlers for appropriate handler, otherwise return.
      """
      bot_id = msg['bot_id']
      if bot_id not in settings.HANDLERS:
        err = "Ignoring message from bot_id %s with no registered handler"
        logger.info(err % bot_id)
        return
      
      def _get_handler(bot_id):
        val = settings.HANDLERS[bot_id]
        if not isinstance(val,tuple): return (val,[])
        return (val[0], val[1:])

      (handler,args) = _get_handler(bot_id)
      module = importlib.import_module(handler)
      #import pdb;pdb.set_trace()
      if not hasattr(module, 'handle_bot_message'):
        err = "Bot handler for %s does not have a handle_bot_msg function"
        logger.warning(err % bot_id)
        return

      handler_fn = getattr(module, 'handle_bot_message')
      try: handler_fn(Message(self._client, msg), *args)
      except:
        err = 'Failed to handle message %s with bot handler "%s"'
        logger.exception(err, msg, handler)
        #logger.exception('\n%s\n' % traceback.format_exc())

    def get_username(self, msg):
      try:
        #import pdb;pdb.set_trace()
        if from_bot(msg):
          username = msg['bot_id']
        else:
          msguser = self._client.users.get(msg['user'])
          username = msguser['name']
      except:
        if 'username' in msg:
          username = msg['username']
        elif 'user' in msg:
          username = msg['user']
        else:
          username = 'NA'
        err = 'Failed to get username for %s'
        logger.exception(err, username)
      msg['username'] = username
      return username


    def get_text(self, msg):
        """Get text from message. If main text is empty, look for text field
        in attachments.
        """
        text = msg.get('text', '')
        if text == '' and 'attachments' in msg:
          try: text = msg['attachments'][0]['text']
          except: text = ''
        return text

    def filter_text(self, msg):
        text = self.get_text(msg)
        logger.info("Got text: %s" % text)
        channel = msg['channel']

        if channel[0] == 'C' or channel[0] == 'G':
            m = AT_MESSAGE_MATCHER.match(text)
            if not m:
                return
            atuser, text = m.groups()
            if atuser != self._client.login_data['self']['id']:
                # a channel message at other user
                return
            logger.debug('got an AT message: %s', text)
            msg['text'] = text
        else:
            m = AT_MESSAGE_MATCHER.match(text)
            if m:
                msg['text'] = m.group(2)
        return msg

    def loop(self):
      while not self._stop.isSet():
        try:
          events = self._client.rtm_read()
        except slacker.Error, e:
          break

        for event in events:
          if event.get('type') != 'message':
            continue
          self._on_new_message(event)
        self._stop.wait(1.0)
      self.stop()

    def stop(self):
      logger.info("Stopping threads")
      if not self._stop.isSet(): self._stop.set()
      if self._client is not None: self._client.stop()
      if self._pool is not None: self._pool.stop()

    def _default_reply(self, msg):
      if 'text' in msg:
        logger.info("Responding to unrecogized command '%s'" %msg['text'])
        #default_reply = [
            #u'Bad command "%s", You can ask me one of the following questions:\n' % msg['text'],
        #]
        #default_reply += [u'    • `{}`'.format(p.pattern) for p in self._plugins.commands['respond_to'].iterkeys()]
      default_reply = "Unrecognized command. Try !help for Panoptez usage"
      self._client.rtm_send_message(msg['channel'], to_utf8(default_reply))
                                     #'\n'.join(to_utf8(default_reply)))


class Message(object):
    def __init__(self, slackclient, body):
        self._client = slackclient
        self._body = body

    def _get_user_id(self):
        if 'user' in self._body:
            return self._body['user']

        return self._client.find_user_by_name(self._body['username'])

    def _gen_at_message(self, text):
        text = u'<@{}>: {}'.format(self._get_user_id(), text)
        return text

    def _gen_reply(self, text):
        chan = self._body['channel']
        if chan.startswith('C') or chan.startswith('G'):
            return self._gen_at_message(text)
        else:
            return text

    def reply_webapi(self, text):
        """
            Send a reply to the sender using Web API

            (This function supports formatted message
            when using a bot integration)
        """
        text = self._gen_reply(text)
        self.send_webapi(text)

    def send_webapi(self, text, attachments=None):
        """
            Send a reply using Web API

            (This function supports formatted message
            when using a bot integration)
        """
        self._client.send_message(
            self._body['channel'],
            to_utf8(text),
            attachments=attachments)

    def reply(self, text):
        """
            Send a reply to the sender using RTM API

            (This function doesn't supports formatted message
            when using a bot integration)
        """
        text = self._gen_reply(text)
        self.send(text)

    def send(self, text):
        """
            Send a reply using RTM API

            (This function doesn't supports formatted message
            when using a bot integration)
        """
        self._client.rtm_send_message(
            self._body['channel'], to_utf8(text))

    @property
    def channel(self):
        return self._client.get_channel(self._body['channel'])

    @property
    def body(self):
        return self._body
