"""Текстовая версия магазина: всё то же, что в Mini App, но прямо в чате.

Нужна на случай, если мини-апп недоступен (нет WEBAPP_URL, старый
клиент, Telegram что-то ограничит) или человеку удобнее кнопками.

Одно сообщение редактируется на месте, длинных списков нет: страны и
лоты листаются страницами по 8, покупки и история — по 6. Логика денег
та же, что у Mini App (shop.py, db.py, crypto.py) — ничего не дублируется.
"""
from __future__ import annotations

import html
import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton as IB, InlineKeyboardMarkup, Message

import bot as b
import config
import emoji
import crypto
import db
import i18n
import lzt
import shop
from countries import COUNTRIES, dial, flag

log = logging.getLogger("numbers.text")
router = Router(name="text")

PER_C, PER_L, PER_O = 8, 6, 6
import countries as _countries
REGIONS = {"all": None} | {k: " ".join(v) for k, v in _countries.REGIONS.items()}
#: Ждём от человека текст: промокод, перевод или своя сумма пополнения.
WAIT: dict[int, tuple[str, float]] = {}

TT: dict[str, dict[str, str]] = {
    "ru": {
        "no_code": "Код ещё не пришёл, попробуйте через 10 секунд", "share": "Поделиться",
        "catalog": "Каталог", "profile": "Профиль", "orders": "Мои покупки", "back": "Назад", "menu": "Меню",
        "cat_title": "Выберите страну", "cat_sub": "Цена «от» — самый дешёвый аккаунт страны. Значок молнии — есть мгновенная выдача.",
        "reg_all": "Весь мир", "reg_cis": "СНГ", "reg_eu": "Европа", "reg_asia": "Азия", "reg_am": "Америка", "reg_af": "Африка",
        "lots": "аккаунтов", "from": "от", "sort_cheap": "Дешевле", "sort_new": "Новые", "sort_old": "Старше сессия",
        "instant": "Мгновенно", "instant_btn": "Мгновенно за {p}", "no_lots": "Сейчас лотов нет — загляните позже.",
        "lot_title": "Telegram-аккаунт", "session": "Сессия", "days": "дн.", "origin": "Происхождение", "premium": "Premium",
        "twofa": "Пароль 2FA", "yes": "есть", "no": "нет", "channels": "Каналы", "contacts": "Контакты", "online": "В сети",
        "checked": "Маркет проверяет аккаунт при покупке. Не работает — вернём деньги.",
        "buy_for": "Купить за {p}", "confirm": "Подтвердите покупку за {p}. Деньги спишутся с баланса.",
        "yes_buy": "Да, купить", "cancel": "Отмена", "buying": "Покупаем на маркете… Обычно 10–30 секунд, пришлём сообщением.",
        "balance": "Баланс", "topup": "Пополнить", "send": "Отправить другу", "promo": "Промокод", "friends": "Друзья",
        "history": "История", "need": "Не хватает {p}. Пополните баланс.",
        "pick_amount": "Сколько пополнить?", "own_amount": "Своя сумма", "pick_method": "Пополнение на {p}. Чем оплатить?",
        "stars_note": "звёзды ×2", "pay": "Оплатить", "check_pay": "Проверить оплату", "paid": "Оплата получена",
        "not_paid": "Оплата ещё не пришла", "ton_hint": "Переведите {a} TON на адрес ниже с комментарием <code>{c}</code>:",
        "ask_amount": "Напишите сумму в рублях, например 300.", "ask_promo": "Пришлите промокод сообщением.",
        "ask_send": "Пришлите ID или @username друга и сумму через пробел, например: <code>@friend 50</code>",
        "promo_ok": "Промокод активирован: +{p}", "send_ok": "Отправлено {p} → {name}",
        "phone": "Номер", "password": "Пароль 2FA", "get_code": "Получить код", "code": "Код входа: <code>{c}</code>",
        "report": "Не работает", "report_ok": "Аккаунт невалиден — деньги вернулись на баланс.",
        "report_valid": "Маркет подтвердил: аккаунт рабочий. Попробуйте войти ещё раз или напишите в поддержку.",
        "report_unknown": "Маркет не ответил. Попробуйте через пару минут.",
        "orders_empty": "Покупок пока нет.", "st_pending": "покупаем", "st_done": "выдан", "st_refunded": "возврат",
        "ref_text": "Пригласите {goal} друзей — получите Telegram-аккаунт бесплатно.\nЗасчитано: <b>{n}/{goal}</b>, приглашено всего: {all}.\n\nВаша ссылка:\n{link}",
        "ref_rule": "Друг засчитывается, когда запустил бота по ссылке и подписан на канал.",
        "ref_claim": "Забрать аккаунт", "page": "стр.",
        "err": "Что-то пошло не так, попробуйте ещё раз.",
    },
    "en": {
        "no_code": "No code yet, try again in 10 seconds", "share": "Share",
        "catalog": "Catalog", "profile": "Profile", "orders": "My purchases", "back": "Back", "menu": "Menu",
        "cat_title": "Choose a country", "cat_sub": "“From” is the cheapest account in the country. The lightning icon means instant delivery.",
        "reg_all": "World", "reg_cis": "CIS", "reg_eu": "Europe", "reg_asia": "Asia", "reg_am": "Americas", "reg_af": "Africa",
        "lots": "accounts", "from": "from", "sort_cheap": "Cheapest", "sort_new": "Newest", "sort_old": "Oldest session",
        "instant": "Instant", "instant_btn": "Instant for {p}", "no_lots": "No listings right now — check back later.",
        "lot_title": "Telegram account", "session": "Session", "days": "d", "origin": "Origin", "premium": "Premium",
        "twofa": "2FA password", "yes": "yes", "no": "no", "channels": "Channels", "contacts": "Contacts", "online": "Online",
        "checked": "The market checks the account on purchase. If it doesn't work, you get your money back.",
        "buy_for": "Buy for {p}", "confirm": "Confirm the purchase for {p}. It will be charged from your balance.",
        "yes_buy": "Yes, buy", "cancel": "Cancel", "buying": "Buying on the market… Usually 10–30 seconds, we'll message you.",
        "balance": "Balance", "topup": "Top up", "send": "Send to a friend", "promo": "Promo code", "friends": "Friends",
        "history": "History", "need": "You need {p} more. Top up your balance.",
        "pick_amount": "How much to top up?", "own_amount": "Custom amount", "pick_method": "Top-up of {p}. How to pay?",
        "stars_note": "Stars ×2", "pay": "Pay", "check_pay": "Check payment", "paid": "Payment received",
        "not_paid": "Payment hasn't arrived yet", "ton_hint": "Send {a} TON to the address below with the comment <code>{c}</code>:",
        "ask_amount": "Send the amount in rubles, e.g. 300.", "ask_promo": "Send the promo code as a message.",
        "ask_send": "Send your friend's ID or @username and the amount, e.g.: <code>@friend 50</code>",
        "promo_ok": "Promo code activated: +{p}", "send_ok": "Sent {p} → {name}",
        "phone": "Number", "password": "2FA password", "get_code": "Get code", "code": "Login code: <code>{c}</code>",
        "report": "Doesn't work", "report_ok": "The account is invalid — your money is back on your balance.",
        "report_valid": "The market confirmed the account works. Try logging in again or contact support.",
        "report_unknown": "The market didn't respond. Try again in a few minutes.",
        "orders_empty": "No purchases yet.", "st_pending": "buying", "st_done": "delivered", "st_refunded": "refunded",
        "ref_text": "Invite {goal} friends and get a Telegram account for free.\nCounted: <b>{n}/{goal}</b>, invited in total: {all}.\n\nYour link:\n{link}",
        "ref_rule": "A friend counts after starting the bot via your link and subscribing to the channel.",
        "ref_claim": "Claim account", "page": "p.",
        "err": "Something went wrong, please try again.",
    },
    "es": {
        "no_code": "Aún no hay código, inténtalo en 10 segundos", "share": "Compartir",
        "catalog": "Catálogo", "profile": "Perfil", "orders": "Mis compras", "back": "Atrás", "menu": "Menú",
        "cat_title": "Elige un país", "cat_sub": "«Desde» es la cuenta más barata del país. El rayo = entrega instantánea.",
        "reg_all": "Mundo", "reg_cis": "CEI", "reg_eu": "Europa", "reg_asia": "Asia", "reg_am": "América", "reg_af": "África",
        "lots": "cuentas", "from": "desde", "sort_cheap": "Más baratas", "sort_new": "Más nuevas", "sort_old": "Sesión antigua",
        "instant": "Al instante", "instant_btn": "Al instante por {p}", "no_lots": "Ahora no hay anuncios, vuelve más tarde.",
        "lot_title": "Cuenta de Telegram", "session": "Sesión", "days": "d", "origin": "Origen", "premium": "Premium",
        "twofa": "Contraseña 2FA", "yes": "sí", "no": "no", "channels": "Canales", "contacts": "Contactos", "online": "En línea",
        "checked": "El mercado verifica la cuenta al comprar. Si no funciona, te devolvemos el dinero.",
        "buy_for": "Comprar por {p}", "confirm": "Confirma la compra por {p}. Se cobrará de tu saldo.",
        "yes_buy": "Sí, comprar", "cancel": "Cancelar", "buying": "Comprando en el mercado… Suele tardar 10–30 segundos, te avisaremos.",
        "balance": "Saldo", "topup": "Recargar", "send": "Enviar a un amigo", "promo": "Código promo", "friends": "Amigos",
        "history": "Historial", "need": "Te faltan {p}. Recarga tu saldo.",
        "pick_amount": "¿Cuánto recargar?", "own_amount": "Otra cantidad", "pick_method": "Recarga de {p}. ¿Cómo pagar?",
        "stars_note": "Stars ×2", "pay": "Pagar", "check_pay": "Comprobar pago", "paid": "Pago recibido",
        "not_paid": "El pago aún no ha llegado", "ton_hint": "Envía {a} TON a la dirección de abajo con el comentario <code>{c}</code>:",
        "ask_amount": "Envía la cantidad en rublos, p. ej. 300.", "ask_promo": "Envía el código promo como mensaje.",
        "ask_send": "Envía el ID o @usuario de tu amigo y la cantidad, p. ej.: <code>@friend 50</code>",
        "promo_ok": "Código activado: +{p}", "send_ok": "Enviado {p} → {name}",
        "phone": "Número", "password": "Contraseña 2FA", "get_code": "Obtener código", "code": "Código de acceso: <code>{c}</code>",
        "report": "No funciona", "report_ok": "La cuenta no es válida: el dinero volvió a tu saldo.",
        "report_valid": "El mercado confirmó que la cuenta funciona. Intenta entrar de nuevo o escribe a soporte.",
        "report_unknown": "El mercado no respondió. Inténtalo en unos minutos.",
        "orders_empty": "Aún no hay compras.", "st_pending": "comprando", "st_done": "entregado", "st_refunded": "reembolsado",
        "ref_text": "Invita a {goal} amigos y recibe una cuenta de Telegram gratis.\nContados: <b>{n}/{goal}</b>, invitados en total: {all}.\n\nTu enlace:\n{link}",
        "ref_rule": "Un amigo cuenta cuando inicia el bot con tu enlace y se suscribe al canal.",
        "ref_claim": "Obtener cuenta", "page": "pág.",
        "err": "Algo salió mal, inténtalo de nuevo.",
    },
    "ar": {
        "no_code": "لم يصل الرمز بعد، حاول بعد 10 ثوانٍ", "share": "مشاركة",
        "catalog": "الكتالوج", "profile": "الملف", "orders": "مشترياتي", "back": "رجوع", "menu": "القائمة",
        "cat_title": "اختر دولة", "cat_sub": "«من» هو أرخص حساب في الدولة. البرق = تسليم فوري.",
        "reg_all": "العالم", "reg_cis": "رابطة الدول", "reg_eu": "أوروبا", "reg_asia": "آسيا", "reg_am": "الأمريكتان", "reg_af": "أفريقيا",
        "lots": "حساب", "from": "من", "sort_cheap": "الأرخص", "sort_new": "الأحدث", "sort_old": "أقدم جلسة",
        "instant": "فوري", "instant_btn": "فوري بـ {p}", "no_lots": "لا توجد عروض الآن — عد لاحقًا.",
        "lot_title": "حساب تيليجرام", "session": "الجلسة", "days": "ي", "origin": "المصدر", "premium": "بريميوم",
        "twofa": "كلمة مرور 2FA", "yes": "نعم", "no": "لا", "channels": "القنوات", "contacts": "جهات الاتصال", "online": "متصل",
        "checked": "يفحص المتجر الحساب عند الشراء. إن لم يعمل نعيد لك المال.",
        "buy_for": "شراء بـ {p}", "confirm": "أكّد الشراء بـ {p}. سيُخصم من رصيدك.",
        "yes_buy": "نعم، اشترِ", "cancel": "إلغاء", "buying": "جارٍ الشراء من المتجر… عادة 10–30 ثانية، سنرسل لك رسالة.",
        "balance": "الرصيد", "topup": "اشحن", "send": "أرسل لصديق", "promo": "رمز ترويجي", "friends": "الأصدقاء",
        "history": "السجل", "need": "ينقصك {p}. اشحن رصيدك.",
        "pick_amount": "كم تريد أن تشحن؟", "own_amount": "مبلغ آخر", "pick_method": "شحن {p}. كيف تدفع؟",
        "stars_note": "النجوم ×2", "pay": "ادفع", "check_pay": "تحقق من الدفع", "paid": "تم استلام الدفع",
        "not_paid": "لم يصل الدفع بعد", "ton_hint": "أرسل {a} TON إلى العنوان أدناه مع التعليق <code>{c}</code>:",
        "ask_amount": "أرسل المبلغ بالروبل، مثل 300.", "ask_promo": "أرسل الرمز الترويجي في رسالة.",
        "ask_send": "أرسل معرّف صديقك أو @اسمه والمبلغ، مثل: <code>@friend 50</code>",
        "promo_ok": "تم تفعيل الرمز: +{p}", "send_ok": "تم إرسال {p} ← {name}",
        "phone": "الرقم", "password": "كلمة مرور 2FA", "get_code": "احصل على الرمز", "code": "رمز الدخول: <code>{c}</code>",
        "report": "لا يعمل", "report_ok": "الحساب غير صالح — أُعيد المال إلى رصيدك.",
        "report_valid": "أكّد المتجر أن الحساب يعمل. حاول الدخول مجددًا أو راسل الدعم.",
        "report_unknown": "لم يرد المتجر. حاول بعد دقائق.",
        "orders_empty": "لا مشتريات بعد.", "st_pending": "جارٍ الشراء", "st_done": "سُلّم", "st_refunded": "مسترد",
        "ref_text": "ادعُ {goal} أصدقاء واحصل على حساب تيليجرام مجانًا.\nالمحتسب: <b>{n}/{goal}</b>، المدعوون: {all}.\n\nرابطك:\n{link}",
        "ref_rule": "يُحتسب الصديق بعد تشغيل البوت عبر رابطك والاشتراك في القناة.",
        "ref_claim": "استلم الحساب", "page": "ص.",
        "err": "حدث خطأ، حاول مرة أخرى.",
    },
    "hi": {
        "no_code": "अभी कोड नहीं आया, 10 सेकंड बाद कोशिश करें", "share": "शेयर करें",
        "catalog": "कैटलॉग", "profile": "प्रोफ़ाइल", "orders": "मेरी खरीदारी", "back": "वापस", "menu": "मेनू",
        "cat_title": "देश चुनें", "cat_sub": "«से» — देश का सबसे सस्ता अकाउंट। बिजली का निशान — तुरंत डिलीवरी।",
        "reg_all": "दुनिया", "reg_cis": "CIS", "reg_eu": "यूरोप", "reg_asia": "एशिया", "reg_am": "अमेरिका", "reg_af": "अफ़्रीका",
        "lots": "अकाउंट", "from": "से", "sort_cheap": "सस्ते", "sort_new": "नए", "sort_old": "पुराना सेशन",
        "instant": "तुरंत", "instant_btn": "तुरंत {p} में", "no_lots": "अभी कोई लिस्टिंग नहीं — बाद में देखें।",
        "lot_title": "Telegram अकाउंट", "session": "सेशन", "days": "दिन", "origin": "स्रोत", "premium": "Premium",
        "twofa": "2FA पासवर्ड", "yes": "हाँ", "no": "नहीं", "channels": "चैनल", "contacts": "संपर्क", "online": "ऑनलाइन",
        "checked": "मार्केट खरीद के समय अकाउंट जाँचता है। काम न करे तो पैसे वापस।",
        "buy_for": "{p} में खरीदें", "confirm": "{p} की खरीद पक्की करें। बैलेंस से कटेगा।",
        "yes_buy": "हाँ, खरीदें", "cancel": "रद्द करें", "buying": "मार्केट से खरीद रहे हैं… आमतौर पर 10–30 सेकंड, हम मैसेज करेंगे।",
        "balance": "बैलेंस", "topup": "टॉप-अप", "send": "दोस्त को भेजें", "promo": "प्रोमो कोड", "friends": "दोस्त",
        "history": "इतिहास", "need": "{p} कम है। बैलेंस टॉप-अप करें।",
        "pick_amount": "कितना टॉप-अप करें?", "own_amount": "अपनी राशि", "pick_method": "{p} का टॉप-अप। कैसे भुगतान करें?",
        "stars_note": "Stars ×2", "pay": "भुगतान करें", "check_pay": "भुगतान जाँचें", "paid": "भुगतान मिला",
        "not_paid": "भुगतान अभी नहीं आया", "ton_hint": "नीचे के पते पर {a} TON टिप्पणी <code>{c}</code> के साथ भेजें:",
        "ask_amount": "रूबल में राशि भेजें, जैसे 300।", "ask_promo": "प्रोमो कोड मैसेज में भेजें।",
        "ask_send": "दोस्त की ID या @username और राशि भेजें, जैसे: <code>@friend 50</code>",
        "promo_ok": "प्रोमो कोड सक्रिय: +{p}", "send_ok": "{p} भेजे → {name}",
        "phone": "नंबर", "password": "2FA पासवर्ड", "get_code": "कोड पाएँ", "code": "लॉगिन कोड: <code>{c}</code>",
        "report": "काम नहीं कर रहा", "report_ok": "अकाउंट अमान्य है — पैसे बैलेंस में वापस।",
        "report_valid": "मार्केट ने पुष्टि की कि अकाउंट चालू है। फिर से लॉग इन करें या सपोर्ट से संपर्क करें।",
        "report_unknown": "मार्केट ने जवाब नहीं दिया। कुछ मिनट बाद कोशिश करें।",
        "orders_empty": "अभी कोई खरीदारी नहीं।", "st_pending": "खरीद रहे हैं", "st_done": "डिलीवर", "st_refunded": "रिफ़ंड",
        "ref_text": "{goal} दोस्तों को बुलाएँ और मुफ़्त Telegram अकाउंट पाएँ।\nगिने गए: <b>{n}/{goal}</b>, कुल बुलाए: {all}।\n\nआपका लिंक:\n{link}",
        "ref_rule": "दोस्त तब गिना जाता है जब वह आपके लिंक से बॉट शुरू करे और चैनल सब्सक्राइब करे।",
        "ref_claim": "अकाउंट लें", "page": "पृ.",
        "err": "कुछ गड़बड़ हुई, फिर से कोशिश करें।",
    },
    "zh": {
        "no_code": "验证码还没到，请 10 秒后再试", "share": "分享",
        "catalog": "商品目录", "profile": "个人中心", "orders": "我的购买", "back": "返回", "menu": "菜单",
        "cat_title": "选择国家", "cat_sub": "「起」为该国最便宜账号的价格。闪电标志 = 即时发货。",
        "reg_all": "全球", "reg_cis": "独联体", "reg_eu": "欧洲", "reg_asia": "亚洲", "reg_am": "美洲", "reg_af": "非洲",
        "lots": "个账号", "from": "起", "sort_cheap": "最便宜", "sort_new": "最新", "sort_old": "会话最久",
        "instant": "即时", "instant_btn": "即时 {p}", "no_lots": "暂无商品，请稍后再来。",
        "lot_title": "Telegram 账号", "session": "会话", "days": "天", "origin": "来源", "premium": "会员",
        "twofa": "两步验证密码", "yes": "有", "no": "无", "channels": "频道", "contacts": "联系人", "online": "在线",
        "checked": "购买时市场会检测账号。不能用就退款。",
        "buy_for": "以 {p} 购买", "confirm": "确认以 {p} 购买，将从余额扣除。",
        "yes_buy": "确认购买", "cancel": "取消", "buying": "正在市场购买…通常 10–30 秒，完成后通知你。",
        "balance": "余额", "topup": "充值", "send": "转给好友", "promo": "优惠码", "friends": "好友",
        "history": "记录", "need": "还差 {p}，请先充值。",
        "pick_amount": "充值多少？", "own_amount": "自定义金额", "pick_method": "充值 {p}，选择支付方式：",
        "stars_note": "Stars ×2", "pay": "去支付", "check_pay": "检查支付", "paid": "已收到付款",
        "not_paid": "尚未收到付款", "ton_hint": "向下方地址转账 {a} TON，备注 <code>{c}</code>：",
        "ask_amount": "请发送卢布金额，例如 300。", "ask_promo": "请发送优惠码。",
        "ask_send": "发送好友的 ID 或 @用户名 和金额，例如：<code>@friend 50</code>",
        "promo_ok": "优惠码已激活：+{p}", "send_ok": "已转出 {p} → {name}",
        "phone": "号码", "password": "两步验证密码", "get_code": "获取验证码", "code": "登录验证码：<code>{c}</code>",
        "report": "无法使用", "report_ok": "账号无效——款项已退回余额。",
        "report_valid": "市场确认账号可用。请再试登录或联系客服。",
        "report_unknown": "市场未响应，请几分钟后再试。",
        "orders_empty": "暂无购买。", "st_pending": "购买中", "st_done": "已发货", "st_refunded": "已退款",
        "ref_text": "邀请 {goal} 位好友即可免费获得 Telegram 账号。\n已计入：<b>{n}/{goal}</b>，共邀请：{all}。\n\n你的链接：\n{link}",
        "ref_rule": "好友通过你的链接启动机器人并订阅频道后才计入。",
        "ref_claim": "领取账号", "page": "页",
        "err": "出错了，请重试。",
    },
}


def _int(v, hi: int = 2 ** 53) -> int:
    """Число из callback_data. Данные кнопок можно подделать — проверяем границы."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if 0 <= n <= hi else 0


def tt(key: str, lang: str, **kw) -> str:
    s = TT.get(lang, TT["en"]).get(key) or TT["en"].get(key, key)
    return s.format(**kw) if kw else s


async def _lang(uid: int) -> str:
    u = await db.get_user(uid)
    return i18n.pick(u["lang"] if u else "en")


def kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def nav(lang: str, back: str) -> list:
    return [b._btn(tt("back", lang), "⬅️", callback_data=back), b._btn(tt("menu", lang), "🏷", callback_data="tm:menu")]


def pager_row(prefix: str, page: int, pages: int) -> list:
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append(IB(text="‹", callback_data=f"{prefix}:{page - 1}"))
    row.append(IB(text=f"{page + 1} / {pages}", callback_data="tm:noop"))
    if page < pages - 1:
        row.append(IB(text="›", callback_data=f"{prefix}:{page + 1}"))
    return row


async def show(c: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    """Редактирует текущее сообщение; если это фото меню — шлёт новое."""
    for t in (text, b._plain(text)):
        try:
            if c.message.photo or c.message.animation:
                await c.message.answer(t, reply_markup=markup)
            else:
                await c.message.edit_text(t, reply_markup=markup)
            return
        except TelegramAPIError as exc:
            if "not modified" in str(exc):
                return
            log.debug("show: %s", exc)
    await c.message.answer(b._plain(text), reply_markup=markup)


def cname(c3: str, lang: str) -> str:
    """Название страны: по-русски из справочника, для остальных языков — по-английски."""
    if lang == "ru":
        return COUNTRIES.get(c3, ("", "", c3))[2]
    return _EN.get(c3, c3)


_EN = {
    "RUS": "Russia", "UKR": "Ukraine", "KAZ": "Kazakhstan", "BLR": "Belarus", "UZB": "Uzbekistan", "KGZ": "Kyrgyzstan",
    "TJK": "Tajikistan", "GEO": "Georgia", "ARM": "Armenia", "AZE": "Azerbaijan", "MDA": "Moldova", "USA": "USA",
    "CAN": "Canada", "GBR": "UK", "DEU": "Germany", "FRA": "France", "ITA": "Italy", "ESP": "Spain", "PRT": "Portugal",
    "NLD": "Netherlands", "POL": "Poland", "CZE": "Czechia", "ROU": "Romania", "TUR": "Turkey", "ISR": "Israel",
    "ARE": "UAE", "SAU": "Saudi Arabia", "EGY": "Egypt", "NGA": "Nigeria", "KEN": "Kenya", "ZAF": "South Africa",
    "GHA": "Ghana", "IND": "India", "PAK": "Pakistan", "BGD": "Bangladesh", "LKA": "Sri Lanka", "NPL": "Nepal",
    "IDN": "Indonesia", "PHL": "Philippines", "VNM": "Vietnam", "THA": "Thailand", "MYS": "Malaysia", "MMR": "Myanmar",
    "KHM": "Cambodia", "LAO": "Laos", "CHN": "China", "JPN": "Japan", "KOR": "South Korea", "BRA": "Brazil",
    "MEX": "Mexico", "ARG": "Argentina", "COL": "Colombia", "PER": "Peru", "CHL": "Chile", "AUS": "Australia",
}


def flag_e(c3: str) -> str:
    """Флаг страны — только премиум-эмодзи (если он есть в паке), иначе ничего."""
    return emoji.tag(flag(c3))


def country_btn(x: dict, lang: str) -> IB:
    text = f"{cname(x['country'], lang)} · {tt('from', lang)} {shop.money(x['from'])}"
    data = f"tm:c:{x['country']}:cheap:0"
    icon = emoji.get(flag(x["country"])) or (emoji.get("⚡") if x["instant"] else None)
    # Есть мгновенная выдача — кнопка синяя; иконка — премиум-флаг или молния.
    return IB(text=text, callback_data=data, icon_custom_emoji_id=icon if b._icons_on() else None,
              style="primary" if x["instant"] else None)


def mask(c3: str, seed: int) -> str:
    n = abs(seed)
    digits = []
    for _ in range(4):
        n = (n * 9301 + 49297) % 233280
        digits.append(str(n % 10))
    return f"+{dial(c3)} {digits[0]}{digits[1]}• ••• ••{digits[2]}{digits[3]}"


# ── Меню и каталог ────────────────────────────────────────────────────

@router.callback_query(F.data == "tm:noop")
async def noop(c: CallbackQuery) -> None:
    await c.answer()


@router.callback_query(F.data == "tm:menu")
async def menu(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    u = await db.get_user(c.from_user.id)
    WAIT.pop(c.from_user.id, None)
    await b.load_menu()
    await show(c, b.menu_text(lang, c.from_user.first_name, int(u["kop"])), b.menu_kb(lang))
    await c.answer()


@router.callback_query(F.data.startswith("tm:cat"))
async def catalog(c: CallbackQuery) -> None:
    # tm:cat:<регион>:<страница>
    parts = c.data.split(":")
    region = parts[2] if len(parts) > 2 and parts[2] in REGIONS else "all"
    page = _int(parts[3], 10 ** 4) if len(parts) > 3 else 0
    lang = await _lang(c.from_user.id)
    home = await shop.home()
    allowed = (REGIONS.get(region) or "").split()
    items = [x for x in home["countries"] if not allowed or x["country"] in allowed]
    pages = max(1, (len(items) + PER_C - 1) // PER_C)
    page = min(max(0, page), pages - 1)
    chunk = items[page * PER_C:(page + 1) * PER_C]
    regs = [IB(text=("• " if r == region else "") + tt(f"reg_{r}", lang), callback_data=f"tm:cat:{r}:0")
            for r in REGIONS]
    rows = [regs[:3], regs[3:]]
    for i in range(0, len(chunk), 2):
        rows.append([country_btn(x, lang) for x in chunk[i:i + 2]])
    rows.append(pager_row(f"tm:cat:{region}", page, pages))
    rows.append([b._btn(tt("orders", lang), "🛒", callback_data="tm:o:0"),
                 b._btn(tt("profile", lang), "👤", callback_data="tm:p")])
    rows.append([b._btn(tt("menu", lang), "🏷", callback_data="tm:menu")])
    text = f"{b._e('🌐')} <b>{tt('cat_title', lang)}</b>\n{tt('cat_sub', lang)}"
    if home.get("demo"):
        text += "\n\n<i>DEMO</i>"
    await show(c, text, kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("tm:c:"))
async def country(c: CallbackQuery) -> None:
    # tm:c:<страна>:<сортировка>:<страница>
    parts = c.data.split(":")
    if len(parts) != 5:
        return await c.answer()
    _, _, c3, sort, page = parts
    page = _int(page, 10 ** 4)
    if sort not in ("cheap", "new", "old"):
        sort = "cheap"
    lang = await _lang(c.from_user.id)
    try:
        lots = await shop.lots(c3, {"sort": sort})
    except Exception as exc:  # noqa: BLE001
        log.warning("лоты %s: %s", c3, exc)
        return await c.answer(tt("err", lang), show_alert=True)
    pages = max(1, (len(lots) + PER_L - 1) // PER_L)
    page = min(max(0, page), pages - 1)
    chunk = lots[page * PER_L:(page + 1) * PER_L]
    home = await shop.home()
    inst = next((x for x in home["instant"] if x["country"] == c3), None)
    rows = []
    if inst:
        rows.append([b._btn(tt("instant_btn", lang, p=shop.money(inst["price"])), "⚡", callback_data=f"tm:bi:{c3}")])
    rows.append([IB(text=("• " if s == sort else "") + tt(f"sort_{s}", lang), callback_data=f"tm:c:{c3}:{s}:0")
                 for s in ("cheap", "new", "old")])
    for x in chunk:
        tags = []
        if x["premium"]:
            tags.append("Premium")
        if x["password"]:
            tags.append("2FA")
        if x["session_days"]:
            tags.append(f"{x['session_days']}{tt('days', lang)}")
        rows.append([IB(text=f"{mask(c3, x['id'])} · {' · '.join(tags) + ' · ' if tags else ''}{shop.money(x['price'])}",
                        callback_data=f"tm:l:{x['id']}")])
    rows.append(pager_row(f"tm:c:{c3}:{sort}", page, pages))
    rows.append(nav(lang, "tm:cat:all:0"))
    text = (f"{flag_e(c3)} <b>{html.escape(cname(c3, lang))}</b> +{dial(c3)}\n"
            f"{len(lots)} {tt('lots', lang)}" + ("" if lots else f"\n\n{tt('no_lots', lang)}"))
    await show(c, text, kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("tm:l:"))
async def lot(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    item_id = _int(c.data.split(":")[2])
    x = shop._cached_lot(item_id)  # noqa: SLF001
    if not shop.allowed_lot(x) or await db.lzt_item_taken(item_id):
        return await c.answer(tt("no_lots", lang), show_alert=True)
    promos = await db.promos()
    price = shop.price_kop(x["cost"], promos.get(x["country"], 0))
    yn = lambda v: tt("yes", lang) if v else tt("no", lang)  # noqa: E731
    seen = int((time.time() - x["last_seen"]) / 86400) if x["last_seen"] else None
    seen_s = "—" if seen is None else f"{seen} {tt('days', lang)}"
    text = (f"{flag_e(x['country'])} <b>{tt('lot_title', lang)}</b>\n<code>{mask(x['country'], x['id'])}</code>\n\n"
            f"{tt('session', lang)}: {x['session_days'] or '—'} {tt('days', lang)}\n"
            f"{tt('online', lang)}: {seen_s}\n"
            f"{tt('origin', lang)}: {x['origin'] or '—'}\n"
            f"{tt('premium', lang)}: {yn(x['premium'])}\n"
            f"{tt('twofa', lang)}: {yn(x['password'])}\n"
            f"{tt('channels', lang)}: {x['channels']} · {tt('contacts', lang)}: {x['contacts']}\n\n"
            f"{b._e('🛡')} {tt('checked', lang)}\n\n<b>{shop.money(price)}</b>")
    rows = [[b._btn(tt("buy_for", lang, p=shop.money(price)), "🛒", callback_data=f"tm:bq:{item_id}:{price}")],
            nav(lang, f"tm:c:{x['country']}:cheap:0")]
    await show(c, text, kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("tm:bq:"))
async def buy_confirm(c: CallbackQuery) -> None:
    parts = c.data.split(":")
    if len(parts) != 4:
        return await c.answer()
    _, _, item_id, price = parts
    item_id, price = str(_int(item_id)), str(_int(price, 10 ** 9))
    lang = await _lang(c.from_user.id)
    u = await db.get_user(c.from_user.id)
    if not u["terms_at"]:
        return await ask_terms(c, lang, f"tm:l:{item_id}")
    if int(u["kop"]) < int(price):
        return await show_topup(c, lang, need=int(price) - int(u["kop"]))
    rows = [[b._btn(tt("yes_buy", lang), "✅", callback_data=f"tm:b:{item_id}:{price}"),
             b._btn(tt("cancel", lang), "⬅️", callback_data=f"tm:l:{item_id}")]]
    await show(c, f"{b._e('🛒')} {tt('confirm', lang, p=shop.money(int(price)))}", kb(rows))
    await c.answer()


LEGAL = {
    "ru": ("Перед первой покупкой примите условия. Аккаунты нельзя использовать для спама, мошенничества и любых "
           "незаконных целей; мы храним, какой номер кому выдан, и блокируем нарушителей.",
           "Принимаю условия", "Условия", "Конфиденциальность", "Покупки для вас закрыты за нарушение условий.",
           "Лимит на сегодня: {n} аккаунтов. Попробуйте завтра."),
    "en": ("Accept the terms before your first purchase. Accounts may not be used for spam, fraud or anything "
           "illegal; we record which number goes to whom and block violators.",
           "I accept", "Terms", "Privacy", "Purchases are closed for you due to a terms violation.",
           "Today's limit: {n} accounts. Try again tomorrow."),
}


def _legal(lang: str) -> tuple:
    return LEGAL["ru" if lang == "ru" else "en"]


async def ask_terms(c: CallbackQuery, lang: str, back: str) -> None:
    text, btn, terms, privacy, _, _ = _legal(lang)
    lg = "ru" if lang == "ru" else "en"
    links = ([IB(text=terms, url=f"{config.WEBAPP_URL}/terms?lang={lg}"),
              IB(text=privacy, url=f"{config.WEBAPP_URL}/privacy?lang={lg}")]
             if config.webapp_enabled() else [IB(text=terms, callback_data="tm:legal:terms"),
                                              IB(text=privacy, callback_data="tm:legal:privacy")])
    await show(c, f"{b._e('🛡')} {text.format(n=config.MAX_PER_DAY)}",
               kb([links, [b._btn(btn, "✅", callback_data=f"tm:acc:{back}")], nav(lang, back)]))
    await c.answer()


@router.callback_query(F.data.startswith("tm:acc:"))
async def accept(c: CallbackQuery) -> None:
    await db.accept_terms(c.from_user.id)
    c_back = c.data[len("tm:acc:"):]
    await c.answer()
    # Возвращаем туда, откуда пришли (карточка лота или страна).
    if c_back.startswith("tm:l:"):
        return await lot(c.model_copy(update={"data": c_back}))
    await menu(c)


@router.callback_query(F.data.startswith("tm:legal:"))
async def legal(c: CallbackQuery) -> None:
    kind = c.data.split(":")[2]
    lang = await _lang(c.from_user.id)
    import re
    body = (config.BASE_DIR / "webapp" / "legal" / f"{kind}.{'ru' if lang == 'ru' else 'en'}.html").read_text(encoding="utf-8")
    text = re.sub(r"<h2>(.*?)</h2>", r"<b>\1</b>", body)
    text = re.sub(r"<h3>(.*?)</h3>", r"\n<b>\1</b>", text)
    text = text.replace("<li>", "• ")
    text = re.sub(r"</?(ul|li|p)[^>]*>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for i in range(0, len(text), 3800):
        await c.message.answer(text[i:i + 3800], disable_web_page_preview=True)
    await c.answer()


def _err_text(e: shop.ShopError, lang: str) -> str:
    if e.code == "banned":
        return _legal(lang)[4]
    if e.code == "day_limit":
        return _legal(lang)[5].format(n=e.extra.get("limit", config.MAX_PER_DAY))
    if e.code == "no_money":
        return tt("need", lang, p=shop.money(int(e.extra.get("need", 0))))
    return tt("err", lang)


@router.callback_query(F.data.startswith("tm:b:"))
async def buy(c: CallbackQuery) -> None:
    parts = c.data.split(":")
    if len(parts) != 4:
        return await c.answer()
    lang = await _lang(c.from_user.id)
    try:
        o = await shop.buy_lot(c.from_user.id, _int(parts[2]), _int(parts[3], 10 ** 9))
    except shop.ShopError as e:
        return await c.answer(_err_text(e, lang), show_alert=True)
    await show(c, f"{b._e('⏰')} {tt('buying', lang)}",
               kb([[b._btn(tt("orders", lang), "🛒", callback_data="tm:o:0")]]))
    await c.answer()
    # Готовый номер придёт уведомлением «done» из shop._fulfil.
    del o


@router.callback_query(F.data.startswith("tm:bi:"))
async def buy_instant(c: CallbackQuery) -> None:
    c3 = c.data.split(":")[2]
    lang = await _lang(c.from_user.id)
    if not (await db.get_user(c.from_user.id))["terms_at"]:
        return await ask_terms(c, lang, f"tm:c:{c3}:cheap:0")
    await c.answer("…")
    try:
        o = await shop.buy_instant(c.from_user.id, c3)
    except shop.ShopError as e:
        if e.code in ("banned", "day_limit"):
            return await c.message.answer(_err_text(e, lang))
        if e.code == "no_money":
            u = await db.get_user(c.from_user.id)
            return await show_topup(c, lang, need=int(e.extra.get("need", 0)) - int(u["kop"]))
        return await c.message.answer(tt("err", lang))
    await order_card(c, lang, int(o["id"]))


# ── Покупки ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tm:o:"))
async def orders(c: CallbackQuery) -> None:
    page = _int(c.data.split(":")[2], 10 ** 4)
    lang = await _lang(c.from_user.id)
    items = await db.user_orders(c.from_user.id)
    pages = max(1, (len(items) + PER_O - 1) // PER_O)
    page = min(max(0, page), pages - 1)
    rows = []
    for o in items[page * PER_O:(page + 1) * PER_O]:
        st = tt(f"st_{o['status']}", lang)
        rows.append([IB(text=f"{o['phone'] or mask(o['country'], o['id'])} · {st}",
                        callback_data=f"tm:od:{o['id']}")])
    rows.append(pager_row("tm:o", page, pages))
    rows.append(nav(lang, "tm:cat:all:0"))
    await show(c, f"{b._e('🛒')} <b>{tt('orders', lang)}</b>" + ("" if items else f"\n\n{tt('orders_empty', lang)}"), kb(rows))
    await c.answer()


async def order_card(c: CallbackQuery, lang: str, oid: int) -> None:
    o = await db.get_order(oid)
    if o is None or int(o["user_id"]) != c.from_user.id:
        return
    v = await shop.order_view(o)
    text = (f"{flag_e(o['country'])} <b>#{oid}</b> · {tt('st_' + o['status'], lang)}\n\n"
            f"{tt('phone', lang)}: <code>{html.escape(o['phone'] or '—')}</code>")
    if o["password"]:
        text += f"\n{tt('password', lang)}: <code>{html.escape(o['password'])}</code>"
    rows = []
    if o["status"] == "done":
        rows.append([b._btn(tt("get_code", lang), "🔑", callback_data=f"tm:code:{oid}")])
        if v["can_report"]:
            rows.append([b._btn(tt("report", lang), "🛡", callback_data=f"tm:rep:{oid}")])
    rows.append(nav(lang, "tm:o:0"))
    await show(c, text, kb(rows))


@router.callback_query(F.data.startswith("tm:od:"))
async def order(c: CallbackQuery) -> None:
    await order_card(c, await _lang(c.from_user.id), _int(c.data.split(":")[2]))
    await c.answer()


@router.callback_query(F.data.startswith("tm:code:"))
async def code(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    try:
        got = await shop.get_code(c.from_user.id, _int(c.data.split(":")[2]))
    except shop.ShopError as e:
        msg = {"no_code": tt("no_code", lang), "slow_down": tt("no_code", lang)}.get(e.code, tt("err", lang))
        return await c.answer(msg, show_alert=e.code not in ("no_code", "slow_down"))
    await c.message.answer(f"{b._e('🔑')} {tt('code', lang, c=html.escape(got['code']))}")
    await c.answer()


@router.callback_query(F.data.startswith("tm:rep:"))
async def report(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    await c.answer("…")
    try:
        res = await shop.report(c.from_user.id, _int(c.data.split(":")[2]))
    except shop.ShopError:
        return await c.message.answer(tt("report_unknown", lang))
    key = {"refunded": "report_ok", "valid": "report_valid"}.get(res["result"], "report_unknown")
    await c.message.answer(f"{b._e('🛡')} {tt(key, lang)}")


# ── Профиль: баланс, пополнение, перевод, промокод, друзья ────────────

@router.callback_query(F.data == "tm:p")
async def profile(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    WAIT.pop(c.from_user.id, None)
    u = await db.get_user(c.from_user.id)
    hist = await db.history(c.from_user.id, 5)
    lines = "\n".join(f"{'+' if h['delta'] > 0 else '−'}{shop.money(abs(h['delta']))} · {h['reason']}" for h in hist)
    text = (f"{b._e('👤')} <b>{html.escape(c.from_user.full_name)}</b> · ID <code>{c.from_user.id}</code>\n\n"
            f"{b._e('💳')} {tt('balance', lang)}: <b>{shop.money(int(u['kop']))}</b>"
            + (f"\n\n<b>{tt('history', lang)}</b>\n{lines}" if lines else ""))
    rows = [[b._btn(tt("topup", lang), "➕", callback_data="tm:t")],
            [b._btn(tt("send", lang), "📢", callback_data="tm:s"), b._btn(tt("promo", lang), "🏷", callback_data="tm:pr")],
            [b._btn(tt("friends", lang), "👥", callback_data="tm:r"), b._btn(tt("orders", lang), "🛒", callback_data="tm:o:0")],
            [IB(text=_legal(lang)[2], callback_data="tm:legal:terms"), IB(text=_legal(lang)[3], callback_data="tm:legal:privacy")],
            [b._btn(tt("menu", lang), "🏷", callback_data="tm:menu")]]
    await show(c, text, kb(rows))
    await c.answer()


async def show_topup(c: CallbackQuery, lang: str, need: int = 0) -> None:
    text = f"{b._e('➕')} <b>{tt('pick_amount', lang)}</b>"
    if need > 0:
        text = f"{tt('need', lang, p=shop.money(need))}\n\n" + text
    amounts = [100, 250, 500, 1000]
    if need > 0:
        amounts = sorted({max(int(config.TOPUP_MIN), -(-need // 100))} | set(amounts))[:4]
    rows = [[IB(text=f"{a} ₽", callback_data=f"tm:ta:{a}") for a in amounts],
            [b._btn(tt("own_amount", lang), "✏️", callback_data="tm:tc")],
            nav(lang, "tm:p")]
    await show(c, text, kb(rows))
    await c.answer()


@router.callback_query(F.data == "tm:t")
async def topup(c: CallbackQuery) -> None:
    await show_topup(c, await _lang(c.from_user.id))


@router.callback_query(F.data == "tm:tc")
async def topup_custom(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    WAIT[c.from_user.id] = ("amount", time.time())
    await c.message.answer(tt("ask_amount", lang))
    await c.answer()


async def methods(target, lang: str, rub: int) -> None:
    rows = []
    for m in crypto.methods():
        label = m["title"] + (f" · {tt('stars_note', lang)}" if m["id"] == "stars" else "")
        rows.append([IB(text=label, callback_data=f"tm:pay:{m['id']}:{rub}")])
    rows.append(nav(lang, "tm:t"))
    text = f"{b._e('💳')} {tt('pick_method', lang, p=f'{rub} ₽')}"
    if isinstance(target, CallbackQuery):
        await show(target, text, kb(rows))
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb(rows))


@router.callback_query(F.data.startswith("tm:ta:"))
async def topup_amount(c: CallbackQuery) -> None:
    await methods(c, await _lang(c.from_user.id), max(1, _int(c.data.split(":")[2], 100_000)))


@router.callback_query(F.data.startswith("tm:pay:"))
async def pay(c: CallbackQuery) -> None:
    parts = c.data.split(":")
    if len(parts) != 4:
        return await c.answer()
    _, _, provider, rub = parts
    rub = str(_int(rub, 100_000))
    lang = await _lang(c.from_user.id)
    try:
        inv = await crypto.create(c.from_user.id, provider[:16], float(rub))
    except crypto.PayError as e:
        msg = str(e)
        return await c.answer(f"min {config.TOPUP_MIN:.0f} ₽" if msg.startswith("min:") else tt("err", lang), show_alert=True)
    if provider == "stars":
        await c.message.answer(f"{b._e('⭐')} {inv['amount']} Stars",
                               reply_markup=kb([[b._btn(f"{tt('pay', lang)} {inv['amount']}", "⭐", url=inv["pay_url"])]]))
        return await c.answer()
    import asyncio
    asyncio.create_task(crypto.watch(inv["invoice_id"]))
    text = f"{b._e('💳')} {inv['title']}: <b>{inv['amount']} {inv['asset']}</b> = {rub} ₽"
    if provider == "ton":
        text += f"\n\n{tt('ton_hint', lang, a=inv['amount'], c=inv['comment'])}\n<code>{inv['wallet']}</code>"
    rows = [[IB(text=tt("pay", lang), url=inv["pay_url"])] if inv["pay_url"] else [],
            [b._btn(tt("check_pay", lang), "🔎", callback_data=f"tm:ck:{inv['invoice_id']}")],
            nav(lang, "tm:p")]
    await show(c, text, kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("tm:ck:"))
async def check_pay(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    inv_id = _int(c.data.split(":")[2])
    row = await db.get_invoice(inv_id)
    if row is None or int(row["user_id"]) != c.from_user.id:
        return await c.answer()
    if row["status"] == "new" and await crypto.check_one(inv_id):
        await crypto.credit(inv_id)
        row = await db.get_invoice(inv_id)
    await c.answer(tt("paid" if row["status"] == "paid" else "not_paid", lang), show_alert=True)


@router.callback_query(F.data == "tm:s")
async def send(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    WAIT[c.from_user.id] = ("send", time.time())
    await c.message.answer(tt("ask_send", lang))
    await c.answer()


@router.callback_query(F.data == "tm:pr")
async def promo(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    WAIT[c.from_user.id] = ("promo", time.time())
    await c.message.answer(tt("ask_promo", lang))
    await c.answer()


@router.callback_query(F.data == "tm:r")
async def friends(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    await shop.ref_confirm(c.from_user.id)
    st = await shop.ref_state(c.from_user.id)
    text = (f"{b._e('👥')} " + tt("ref_text", lang, goal=st["goal"], p=shop.money(int(st["prize_max"] * 100)),
                                  n=st["progress"], all=st["invited"], link=html.escape(st["link"]))
            + (f"\n\n<i>{tt('ref_rule', lang)}</i>" if st["need_channel"] else ""))
    rows = [[b._btn(tt("share", lang), "📢", url=f"https://t.me/share/url?url={st['link']}")]
            if st["link"].startswith("http") else [],
            [b._btn(tt("ref_claim", lang), "🎁", callback_data="tm:rc")] if st["claimable"] else [],
            nav(lang, "tm:p")]
    await show(c, text, kb(rows))
    await c.answer()


@router.callback_query(F.data == "tm:rc")
async def ref_claim(c: CallbackQuery) -> None:
    lang = await _lang(c.from_user.id)
    await c.answer("…")
    try:
        o = await shop.ref_claim(c.from_user.id)
    except shop.ShopError:
        return await c.message.answer(tt("err", lang))
    await order_card(c, lang, int(o["id"]))


# ── Текстовые ответы: своя сумма, перевод, промокод ───────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def waiting(m: Message) -> None:
    got = WAIT.get(m.from_user.id)
    if not got or time.time() - got[1] > 600:
        WAIT.pop(m.from_user.id, None)
        return
    kind = got[0]
    lang = await _lang(m.from_user.id)
    text = (m.text or "").strip()
    if kind == "amount":
        try:
            rub = int(float(text.replace(",", ".").replace("₽", "").strip()[:12]))
        except (ValueError, OverflowError):
            return await m.answer(tt("ask_amount", lang))
        if rub > 100_000:
            return await m.answer(tt("ask_amount", lang))
        if rub < config.TOPUP_MIN:
            return await m.answer(f"min {config.TOPUP_MIN:.0f} ₽")
        WAIT.pop(m.from_user.id, None)
        return await methods(m, lang, rub)
    if kind == "promo":
        WAIT.pop(m.from_user.id, None)
        try:
            res = await shop.promo(m.from_user.id, text)
        except shop.ShopError:
            return await m.answer(tt("err", lang))
        return await m.answer(tt("promo_ok", lang, p=shop.money(res)))
    if kind == "send":
        parts = text.split()
        try:
            to, amount = parts[0], float(parts[1].replace(",", ".")[:12])
        except (IndexError, ValueError):
            return await m.answer(tt("ask_send", lang))
        import math
        if not math.isfinite(amount):
            return await m.answer(tt("ask_send", lang))
        kop = int(round(amount * 100))
        try:
            res = await shop.transfer(m.from_user.id, to, kop)
        except shop.ShopError as e:
            if e.code == "no_money":
                return await m.answer(tt("need", lang, p=shop.money(kop)))
            return await m.answer(tt("err", lang))
        WAIT.pop(m.from_user.id, None)
        return await m.answer(tt("send_ok", lang, p=shop.money(kop), name=html.escape(str(res["to"]))))
