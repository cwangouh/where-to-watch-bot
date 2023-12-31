from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiohttp import ClientSession

from cinemabot.bot.bot_utils import *
from cinemabot.repository import DBManager
from cinemabot.scraper.scraper import FilmScraper


# TODO Сделать ChatMemberUpdated функцию для обработки новичков (Можно было бы добавлять в БД)
class CinemaBot:
    def __init__(self, token: str, dispatcher: Dispatcher, db_manager: DBManager, session: ClientSession) -> None:
        self.bot = Bot(token, parse_mode=ParseMode.HTML)
        self.db_manager: DBManager = db_manager
        self.dp: Dispatcher = dispatcher
        self.scraper: FilmScraper = FilmScraper(session)
        self.help = HelpCommandUtils.make_help_list(self)

        self.dp.message(F.text.regexp(r"^[\w\s\.\?!,';:\$%]+$"))(self.command_find_handler)
        self.dp.message(Command("find"))(self.command_find_handler)
        self.dp.message(Command(re.compile(r"give_(\d+)")))(self.command_give_handler)
        self.dp.message(Command("help"))(self.command_help_handler)
        self.dp.message(Command("history"))(self.command_history_handler)
        self.dp.message(CommandStart())(self.command_start_handler)

    async def command_find_handler(self, message: types.Message) -> None:
        """
        Looks for links to online cinemas by film title sent. This is the default command,
        meaning you just need to send the movie title. But you can still use /find.

        :RU Ищет ссылки на онлайн-кинотеатры по заданному названию фильма. Это команда по умолчанию,
        то есть достаточно просто послать название фильма. Однако все равно можно использовать /find
        в начале запроса.

        :param message: message received
        :return: None
        """
        user_id = message.from_user.id
        input_title = message.text.removeprefix("/find").strip()
        if not input_title:
            await message.answer(ErrorUtils.make_i_expected_reply("название фильма..."))
            return

        # TODO Add similar titles handling without going to Google
        wiki_title = await self.scraper.get_wiki_title(input_title)
        film_list = self.db_manager.find_film_by_name(wiki_title)
        if not film_list:
            info = await self.scraper.lookup(wiki_title, normalize=False)
            inserted_film_id = self.db_manager.insert_film(info)
            await self.reply_and_create_request(message, info, film_id=inserted_film_id, user_id=user_id)
            return

        film = film_list[0]
        film_id = int(film[0])
        requests = self.db_manager.find_requests_by_film_id_and_user_id(film_id, user_id)
        if not requests:  # Film could have been added by another user
            info = {
                "title": film[1],
                "genre": film[2],
                "year": film[3],
                "links": film[4],
                "info": film[5],
                "rate": film[6],
                "poster": film[7]
            }
            await self.reply_and_create_request(message, info, film_id=film_id, user_id=user_id)
        else:
            request = requests[0]
            message_id = int(request[3])
            chat_id = message.chat.id

            self.db_manager.insert_request(
                film_id,
                user_id,
                message_id
            )
            await self.bot.forward_message(chat_id, chat_id, message_id)

    async def reply_and_create_request(self, message: Message, info: dict[str, str | None], film_id: int, user_id: int):
        result_message = await message.answer(FindCommandUtils.make_find_reply(info))
        self.db_manager.insert_request(
            film_id,
            user_id,
            result_message.message_id
        )

    async def command_history_handler(self, message: Message) -> None:
        """
        Shows search history.
        :RU Показывает историю поиска.

        :param message: message received
        :return: None
        """
        limit = 10
        output = self.db_manager.find_recent_films_by_user_id_with_limit(message.from_user.id, limit)
        reply = HistoryCommandUtils.make_history_reply(output, limit=limit)
        await message.answer(reply)

    async def command_start_handler(self, message: Message) -> None:
        """
        Greets user.
        :RU Приветствует пользователя.

        :param message: message received
        :return: None
        """
        await message.answer(StartCommandUtils.make_start_reply(message))

    async def command_help_handler(self, message: Message) -> None:
        """
        Shows a list of available commands.
        :RU Показывает список доступных команд.

        :param message: message received
        :return: None
        """
        await message.answer(self.help)

    async def command_give_handler(self, message: Message) -> None:
        """
        Forwards specified message. Usage - /give_[message_id]
        :RU Посылает указанное сообщение. Использование - /give_[message_id]

        :param message: message received
        :return: None
        """
        command = message.text.split()[0]
        message_id = int(command.split("_")[1])
        chat_id = message.chat.id
        user_id = message.from_user.id

        result_message = await self.bot.forward_message(chat_id, chat_id, message_id)
        requests = self.db_manager.find_requests_by_reply_message_id_and_user_id(message_id, user_id)
        film_id = requests[0][1]

        self.db_manager.insert_request(
            film_id,
            user_id,
            result_message.message_id
        )

    async def run(self) -> None:
        await self.dp.start_polling(self.bot)
