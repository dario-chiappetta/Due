"""
Serve a Due :class:`due.agent.Agent` over XMPP by logging into a server with an
authorized account.

.. warning::

	XMPP support is for testing purposes and is not production ready.
	Particularly, the current implementation is obsolete, it cannot handle more
	than one episode at the same time, and does not tell users apart (incoming
	messages will be regarded as if they were sent by a fake account
	`default@human.im`).

This is how you serve a toy agent on XMPP

.. code-block:: python

    # Instantiate an Agent
	from due.models.tfidf import TfIdfAgent
	agent = TfIdfAgent()

	# Learn episodes from a toy corpus
	from due.corpora import toy as toy_corpus
	agent.learn_episodes(toy_corpus.episodes())

	# Connect bot
	from due.serve import xmpp
	xmpp.serve(agent, "<XMPP_ACCOUNT_USERNAME>", "<XMPP_ACCOUNT_PASSWORD>")

API
===
"""

import logging
import uuid
from datetime import datetime

from due.agent import Agent
from due.models.tfidf import TfIdfAgent
from due.models.dummy import DummyAgent
from due.episode import LiveEpisode
from due.event import Event

from sleekxmpp import ClientXMPP
from sleekxmpp.exceptions import IqError, IqTimeout


class DueBot(ClientXMPP, Agent):

	DEFAULT_HUMAN_JID = "default@human.im"

	def __init__(self, agent, jid, password):
		"""
		Expose an :class:`due.agent.Agent` on XMPP with the given credentials.

		:param agent: An Agent
		:type agent: :class:`due.agent.Agent`
		:param jid: A Jabber ID
		:type jid: :class:`str`
		:param password: The Jabber account password
		:type password: :class:`str`
		"""
		ClientXMPP.__init__(self, jid, password)
		Agent.__init__(self, agent.id)

		self._agent = agent

		self._humans = {}
		self._live_episode = None
		self._last_message = None
		self._logger = logging.getLogger(__name__ + ".DueBot")

		self.add_event_handler("session_start", self.session_start)
		self.add_event_handler("message", self.message)

	def session_start(self, event):
		self.send_presence()
		self.get_roster()

	def message(self, msg):
		if msg['type'] in ('chat', 'normal'):
			human_agent = self._fetch_or_create_human_agent(DueBot.DEFAULT_HUMAN_JID)
			self._last_message = msg
			if self._handle_command_message(msg):
				return
			if self._live_episode is None:
				self._live_episode = LiveEpisode(human_agent, self)
				# self._live_episode = LiveEpisode(human_agent, self._agent)
			utterance = Event(Event.Type.Utterance, datetime.now(), str(human_agent.id), msg['body'])
			self._live_episode.add_event(utterance)

	def utterance_callback(self, episode):
		"""See :meth:`due.agent.Agent.utterance_callback`"""
		self._logger.info("Received utterance")
		answers = self._agent.utterance_callback(episode)
		self.act_events(answers, episode)

	def act_events(self, events, episode):
		for e in events:
			if e.type == Event.Type.Action:
				e.payload.run()
			elif e.type == Event.Type.Utterance:
				if self._last_message is None:
					self._logger.warning("Could not send message '%s' because \
						no last message is set. This is not supposed to happen.", e.payload)
					return
				self._logger.info("Sending reply on chat: %s", e)
				self._last_message.reply(e.payload).send()

			episode.add_event(e)

	def say(self, sentence, episode):
		"""
		Deprecated!
		"""
		self._logger.warn('deprecated use of DueBot.say(). Please use DueBot.act_events() instead.')
		if self._last_message is None:
			self._logger.warning("Could not send message '%s' because \
				no last message is set. This is not supposed to happen.", sentence)
			return
		self._last_message.reply(sentence).send()
		episode.add_utterance(self._agent, sentence)

	def _fetch_or_create_human_agent(self, jid):
		if jid not in self._humans:
			self._humans[jid] = DummyAgent(jid)
		return self._humans[jid]

	def _handle_command_message(self, msg):
		"""
		Command messages are:

			* `,,,leave`: closes the episode
		"""
		if msg['body'][0:3] != ',,,': return False
		if msg['body'] == ',,,leave':
			msg.reply("[you left the episode]").send()
			human_agent = self._fetch_or_create_human_agent(DueBot.DEFAULT_HUMAN_JID)
			leave_event = Event(Event.Type.Leave, datetime.now(), str(human_agent.id), None)
			self._live_episode.add_event(leave_event)
			self._live_episode = None
			self._last_message = None
		return True

	def save(self):
		raise NotImplementedError()

	def learn_episodes(self, episodes):
		raise NotImplementedError()

	def new_episode_callback(self, new_episode):
		self._logger.info("New episode callback received: %s", new_episode)

	def action_callback(self, episode):
		raise NotImplementedError()

	def leave_callback(self, episode):
		self._logger.info("Leave callback received: %s", episode)

def serve(agent, jid, password):
	"""
	Expose an :class:`due.agent.Agent` on XMPP with the given credentials.

	:param agent: An Agent
	:type agent: :class:`due.agent.Agent`
	:param jid: A Jabber ID
	:type jid: :class:`str`
	:param password: The Jabber account password
	:type password: :class:`str`
	"""
	bot = DueBot(agent, jid, password)
	bot.connect()
	bot.process(block=True)
