"""Тексты бота: русский + 5 самых распространённых языков мира
(английский, китайский, хинди, испанский, арабский). Витрина — webapp/i18n.js.

Язык берётся из language_code Telegram, его можно сменить кнопкой.
Языки СНГ получают русский, остальные — английский.
"""
from __future__ import annotations

LANGS = {
    "ru": "Русский", "en": "English", "zh": "中文", "hi": "हिन्दी", "es": "Español", "ar": "العربية",
}

# Ключи: hi — приветствие (заголовок), menu — текст меню, open — кнопка
# маркета, howto — обучение, gw — конкурс, lang — язык, support,
# tour — шаги обучения, done/refund/won/topup — уведомления, gw_new — анонс.
T: dict[str, dict[str, str]] = {
    "en": {
        "ref_new": "{name} joined via your link. They'll count once they subscribe to the channel.",
        "ref_ok": "{name} subscribed to the channel and counts as your friend: {n}/{goal}. Every {goal} friends = a free Telegram account.",
        "received": "{name} sent you {amount}. It's already on your balance.",
        "hi": "Welcome, {name}!",
        "menu": "Telegram accounts from 50+ countries. Prices are just 10% above the market, delivery is instant, every account is checked.",
        "open": "Open market", "howto": "How to buy", "gw": "Daily giveaway", "lang": "Language", "support": "Support",
        "tour": "1. Top up your balance: CryptoBot, xRocket, Tonkeeper or Stars.\n2. Open the market and pick a country — use filters and price sorting.\n3. Tap «Buy»: the number appears in «My purchases».\n4. Log in to Telegram with this number and tap «Get code» — the code shows up right in the app.",
        "done": "Order #{order} is ready: <code>{phone}</code>\nOpen «My purchases» to get the login code.",
        "refund": "Order #{order} could not be completed — {amount} is back on your balance.",
        "won": "You won today's giveaway! The account is in «My purchases» (order #{order}).",
        "topup": "Balance topped up: +{amount}",
        "gw_new": "A new giveaway has started: a free Telegram account every day. Subscribe to our channel and join in the app.",
        "gw_res": "Today's giveaway winner: {name}. A new draw is already open — join!",
    },
    "ru": {
        "ref_new": "{name} пришёл(а) по вашей ссылке. Друг засчитается, как только подпишется на канал.",
        "ref_ok": "{name} подписался(ась) на канал — друг засчитан: {n}/{goal}. Каждые {goal} друзей = бесплатный Telegram-аккаунт.",
        "received": "{name} отправил(а) вам {amount}. Уже на балансе.",
        "hi": "Добро пожаловать, {name}!",
        "menu": "Telegram-аккаунты 50+ стран. Цена всего на 10% выше маркета, выдача мгновенная, каждый аккаунт проверен.",
        "open": "Открыть маркет", "howto": "Как купить", "gw": "Конкурс дня", "lang": "Язык", "support": "Поддержка",
        "tour": "1. Пополните баланс: CryptoBot, xRocket, Tonkeeper или звёзды.\n2. Откройте маркет и выберите страну — есть фильтры и сортировка по цене.\n3. Нажмите «Купить»: номер появится в «Мои покупки».\n4. Войдите в Telegram по этому номеру и нажмите «Получить код» — код придёт прямо в приложение.",
        "done": "Заказ #{order} готов: <code>{phone}</code>\nКод для входа — в разделе «Мои покупки».",
        "refund": "Заказ #{order} не удалось выполнить — {amount} вернулись на баланс.",
        "won": "Вы выиграли конкурс дня! Аккаунт уже в «Мои покупки» (заказ #{order}).",
        "topup": "Баланс пополнен: +{amount}",
        "gw_new": "Начался новый конкурс: каждый день разыгрываем Telegram-аккаунт. Подпишитесь на канал и участвуйте в приложении.",
        "gw_res": "Победитель конкурса дня: {name}. Новый розыгрыш уже открыт — участвуйте!",
    },
    "es": {
        "ref_new": "{name} se unió con tu enlace. Contará en cuanto se suscriba al canal.",
        "ref_ok": "{name} se suscribió al canal y cuenta como tu amigo: {n}/{goal}. Cada {goal} amigos = una cuenta de Telegram gratis.",
        "received": "{name} te envió {amount}. Ya está en tu saldo.",
        "hi": "¡Bienvenido, {name}!",
        "menu": "Cuentas de Telegram de más de 50 países. Solo un 10% sobre el precio del mercado, entrega instantánea, cada cuenta verificada.",
        "open": "Abrir mercado", "howto": "Cómo comprar", "gw": "Sorteo diario", "lang": "Idioma", "support": "Soporte",
        "tour": "1. Recarga tu saldo: CryptoBot, xRocket, Tonkeeper o Stars.\n2. Abre el mercado y elige un país — hay filtros y orden por precio.\n3. Pulsa «Comprar»: el número aparece en «Mis compras».\n4. Inicia sesión en Telegram con ese número y pulsa «Obtener código».",
        "done": "El pedido #{order} está listo: <code>{phone}</code>\nEl código de acceso está en «Mis compras».",
        "refund": "No se pudo completar el pedido #{order}: {amount} volvieron a tu saldo.",
        "won": "¡Ganaste el sorteo de hoy! La cuenta está en «Mis compras» (pedido #{order}).",
        "topup": "Saldo recargado: +{amount}",
        "gw_new": "Nuevo sorteo: cada día regalamos una cuenta de Telegram. Suscríbete al canal y participa en la app.",
        "gw_res": "Ganador del sorteo de hoy: {name}. ¡El nuevo sorteo ya está abierto!",
    },
    "ar": {
        "ref_new": "انضم {name} عبر رابطك. سيُحتسب بمجرد اشتراكه في القناة.",
        "ref_ok": "اشترك {name} في القناة وتم احتسابه: {n}/{goal}. كل {goal} أصدقاء = حساب تيليجرام مجاني.",
        "received": "أرسل لك {name} مبلغ {amount}. أصبح في رصيدك.",
        "hi": "مرحبًا، {name}!",
        "menu": "حسابات تيليجرام من أكثر من 50 دولة. السعر أعلى من السوق بـ10% فقط، تسليم فوري، وكل حساب مُفحوص.",
        "open": "افتح المتجر", "howto": "طريقة الشراء", "gw": "سحب اليوم", "lang": "اللغة", "support": "الدعم",
        "tour": "1. اشحن رصيدك: CryptoBot أو xRocket أو Tonkeeper أو النجوم.\n2. افتح المتجر واختر دولة — مع فلاتر وترتيب حسب السعر.\n3. اضغط «شراء»: يظهر الرقم في «مشترياتي».\n4. سجّل الدخول إلى تيليجرام بهذا الرقم واضغط «احصل على الرمز».",
        "done": "الطلب #{order} جاهز: <code>{phone}</code>\nرمز الدخول في «مشترياتي».",
        "refund": "تعذّر تنفيذ الطلب #{order} — أُعيد {amount} إلى رصيدك.",
        "won": "فزت بسحب اليوم! الحساب في «مشترياتي» (الطلب #{order}).",
        "topup": "تم شحن الرصيد: +{amount}",
        "gw_new": "بدأ سحب جديد: حساب تيليجرام مجاني كل يوم. اشترك في القناة وشارك من التطبيق.",
        "gw_res": "فائز سحب اليوم: {name}. السحب الجديد مفتوح الآن!",
    },
    "hi": {
        "ref_new": "{name} आपके लिंक से जुड़े। चैनल सब्सक्राइब करते ही गिने जाएँगे।",
        "ref_ok": "{name} ने चैनल सब्सक्राइब किया — दोस्त गिना गया: {n}/{goal}। हर {goal} दोस्त = एक मुफ़्त Telegram अकाउंट।",
        "received": "{name} ने आपको {amount} भेजे। बैलेंस में जुड़ गए।",
        "hi": "स्वागत है, {name}!",
        "menu": "50+ देशों के Telegram अकाउंट। बाज़ार से सिर्फ़ 10% ज़्यादा, तुरंत डिलीवरी, हर अकाउंट जाँचा हुआ।",
        "open": "मार्केट खोलें", "howto": "कैसे खरीदें", "gw": "आज का गिवअवे", "lang": "भाषा", "support": "सहायता",
        "tour": "1. बैलेंस टॉप-अप करें: CryptoBot, xRocket, Tonkeeper या Stars.\n2. मार्केट खोलें और देश चुनें — फ़िल्टर और कीमत से सॉर्ट।\n3. «खरीदें» दबाएँ: नंबर «मेरी खरीदारी» में आ जाएगा।\n4. इस नंबर से Telegram में लॉग इन करें और «कोड पाएँ» दबाएँ।",
        "done": "ऑर्डर #{order} तैयार है: <code>{phone}</code>\nलॉगिन कोड «मेरी खरीदारी» में है।",
        "refund": "ऑर्डर #{order} पूरा नहीं हो सका — {amount} बैलेंस में वापस।",
        "won": "आपने आज का गिवअवे जीता! अकाउंट «मेरी खरीदारी» में है (ऑर्डर #{order})।",
        "topup": "बैलेंस टॉप-अप: +{amount}",
        "gw_new": "नया गिवअवे शुरू: हर दिन एक मुफ़्त Telegram अकाउंट। चैनल सब्सक्राइब करें और ऐप में भाग लें।",
        "gw_res": "आज के विजेता: {name}। नया ड्रॉ खुला है!",
    },
    "zh": {
        "ref_new": "{name} 通过你的链接加入。订阅频道后即计入。",
        "ref_ok": "{name} 已订阅频道，计为你的好友：{n}/{goal}。每 {goal} 位好友 = 一个免费 Telegram 账号。",
        "received": "{name} 向你转了 {amount}，已到账。",
        "hi": "欢迎，{name}！",
        "menu": "来自 50 多个国家的 Telegram 账号。仅比市场价高 10%，即时发货，每个账号均已检测。",
        "open": "打开商城", "howto": "如何购买", "gw": "每日抽奖", "lang": "语言", "support": "客服",
        "tour": "1. 充值余额：CryptoBot、xRocket、Tonkeeper 或 Stars。\n2. 打开商城选择国家——支持筛选和按价格排序。\n3. 点击「购买」：号码会出现在「我的购买」。\n4. 用该号码登录 Telegram，点击「获取验证码」。",
        "done": "订单 #{order} 已完成：<code>{phone}</code>\n登录验证码在「我的购买」中。",
        "refund": "订单 #{order} 未能完成——{amount} 已退回余额。",
        "won": "你赢得了今日抽奖！账号在「我的购买」中（订单 #{order}）。",
        "topup": "余额已充值：+{amount}",
        "gw_new": "新抽奖开始：每天送出一个 Telegram 账号。订阅频道并在应用内参与。",
        "gw_res": "今日中奖者：{name}。新一轮已开启！",
    },
}


def pick(code: str | None) -> str:
    code = (code or "").lower().split("-")[0]
    if code in T:
        return code
    return "ru" if code in ("uk", "be", "kk", "uz", "ky", "tg", "hy", "ka", "az", "tk", "mo") else "en"


def t(key: str, lang: str | None, **kw) -> str:
    lang = pick(lang)
    text = T[lang].get(key) or T["en"].get(key) or key
    return text.format(**kw) if kw else text
