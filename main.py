from keep_alive import keep_alive
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext, ConversationHandler
from datetime import datetime, timedelta
from persiantools.jdatetime import JalaliDate
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
import os
import sys

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# حالت‌های گفتگو
(
    ADD_CLIENT, ADD_CURRENCY, ADD_AMOUNT, ADD_SCHEDULE, ADD_TIME,
    RECORD_PAYMENT, PAYMENT_AMOUNT,
    RESCHEDULE, NEW_TIME,
    CANCEL_SESSION, CANCEL_CONFIRM,
    ADD_EXTRA_SESSION, EXTRA_SESSION_TIME,
    CHANGE_PAYMENT_AMOUNT, NEW_PAYMENT_AMOUNT,
    REPORT_TYPE, REPORT_PERIOD
) = range(17)

# دیتابیس ساده با DataFrame
try:
    df_clients = pd.read_pickle('clients_data.pkl')
except FileNotFoundError:
    df_clients = pd.DataFrame(columns=[
        'client_name', 'currency', 'session_fee', 'schedule_type', 
        'next_session', 'sessions_count', 'cancellations', 
        'reschedules', 'payments', 'balance', 'active'
    ])

try:
    df_sessions = pd.read_pickle('sessions_data.pkl')
except FileNotFoundError:
    df_sessions = pd.DataFrame(columns=[
        'client_name', 'session_date', 'session_time', 
        'duration', 'status', 'payment', 'notes'
    ])

try:
    df_payments = pd.read_pickle('payments_data.pkl')
except FileNotFoundError:
    df_payments = pd.DataFrame(columns=[
        'client_name', 'payment_date', 'amount', 
        'currency', 'method', 'notes'
    ])

# ذخیره داده‌ها
def save_data():
    df_clients.to_pickle('clients_data.pkl')
    df_sessions.to_pickle('sessions_data.pkl')
    df_payments.to_pickle('payments_data.pkl')

# توابع کمکی
def to_jalali(dt):
    return JalaliDate(dt)

def format_time(time_str):
    try:
        return datetime.strptime(time_str, '%H:%M').strftime('%H:%M')
    except:
        return None

def get_client(name):
    return df_clients[df_clients['client_name'] == name].iloc[0] if name in df_clients['client_name'].values else None

def update_client(name, **kwargs):
    global df_clients
    idx = df_clients[df_clients['client_name'] == name].index
    if len(idx) > 0:
        for key, value in kwargs.items():
            df_clients.at[idx[0], key] = value
        save_data()

# دستورات ربات
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    update.message.reply_text(
        f"سلام دکتر {user.first_name}👋\n"
        "ربات مدیریت مراجعان و پرداخت‌ها آماده خدمت است.\n\n"
        "دستورات اصلی:\n"
        "/add_client - افزودن مراجع جدید\n"
        "/record_payment - ثبت پرداخت\n"
        "/reschedule - تغییر زمان جلسه\n"
        "/cancel_session - کنسل کردن جلسه\n"
        "/add_extra - افزودن جلسه اضافه\n"
        "/change_fee - تغییر مبلغ پرداختی\n"
        "/client_report - گزارش مراجع\n"
        "/financial_report - گزارش مالی\n"
        "/schedule_report - گزارش برنامه زمانی\n"
        "/end_client - اتمام جلسات مراجع"
    )

def add_client(update: Update, context: CallbackContext) -> int:
    update.message.reply_text('لطفاً نام مراجع را وارد کنید:')
    return ADD_CLIENT

def add_client_name(update: Update, context: CallbackContext) -> int:
    context.user_data['client_name'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("تومان", callback_data='IRR')],
        [InlineKeyboardButton("دلار", callback_data='USD')],
        [InlineKeyboardButton("یورو", callback_data='EUR')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text('واحد مالی پرداختی را انتخاب کنید:', reply_markup=reply_markup)
    return ADD_CURRENCY

def add_currency(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    context.user_data['currency'] = query.data
    query.edit_message_text(f"واحد مالی انتخاب شده: {query.data}")
    query.message.reply_text('مبلغ پرداختی برای هر جلسه را وارد کنید:')
    return ADD_AMOUNT

def add_amount(update: Update, context: CallbackContext) -> int:
    try:
        amount = float(update.message.text)
        context.user_data['session_fee'] = amount

        keyboard = [
            [InlineKeyboardButton("هفتگی", callback_data='weekly')],
            [InlineKeyboardButton("دو هفته یکبار", callback_data='biweekly')],
            [InlineKeyboardButton("متغیر", callback_data='variable')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        update.message.reply_text('نوع برنامه جلسات را انتخاب کنید:', reply_markup=reply_markup)
        return ADD_SCHEDULE
    except ValueError:
        update.message.reply_text('لطفاً یک عدد معتبر وارد کنید:')
        return ADD_AMOUNT

def add_schedule(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    context.user_data['schedule_type'] = query.data
    query.edit_message_text(f"نوع برنامه انتخاب شده: {query.data}")
    query.message.reply_text('زمان اولین جلسه را وارد کنید (مثال: 1403-05-15 14:30):')
    return ADD_TIME

def add_time(update: Update, context: CallbackContext) -> int:
    try:
        date_str, time_str = update.message.text.split()
        year, month, day = map(int, date_str.split('-'))
        hour, minute = map(int, time_str.split(':'))

        jalali_date = JalaliDate(year, month, day)
        gregorian_date = jalali_date.to_gregorian()
        session_time = datetime.combine(gregorian_date, datetime.min.time()) + timedelta(hours=hour, minutes=minute)

        # افزودن مراجع به دیتابیس
        global df_clients
        new_client = {
            'client_name': context.user_data['client_name'],
            'currency': context.user_data['currency'],
            'session_fee': context.user_data['session_fee'],
            'schedule_type': context.user_data['schedule_type'],
            'next_session': session_time,
            'sessions_count': 0,
            'cancellations': 0,
            'reschedules': 0,
            'payments': 0,
            'balance': -context.user_data['session_fee'],  # بدهکار برای اولین جلسه
            'active': True
        }

        df_clients = pd.concat([df_clients, pd.DataFrame([new_client])], ignore_index=True)

        # افزودن جلسه به دیتابیس جلسات
        global df_sessions
        new_session = {
            'client_name': context.user_data['client_name'],
            'session_date': session_time.date(),
            'session_time': session_time.time(),
            'duration': 60,  # مدت زمان پیش‌فرض 60 دقیقه
            'status': 'scheduled',
            'payment': 0,
            'notes': 'جلسه اول'
        }

        df_sessions = pd.concat([df_sessions, pd.DataFrame([new_session])], ignore_index=True)

        save_data()

        update.message.reply_text(
            f"مراجع {context.user_data['client_name']} با موفقیت اضافه شد.\n"
            f"اولین جلسه در تاریخ {date_str} ساعت {time_str} تنظیم شد."
        )

        return ConversationHandler.END
    except Exception as e:
        update.message.reply_text('فرمت تاریخ/زمان نامعتبر است. لطفاً به شکل مثال وارد کنید (1403-05-15 14:30):')
        return ADD_TIME

def record_payment(update: Update, context: CallbackContext) -> int:
    if len(df_clients) == 0:
        update.message.reply_text('هنوز مراجعی ثبت نشده است.')
        return ConversationHandler.END

    client_list = "\n".join(df_clients['client_name'].tolist())
    update.message.reply_text(f"نام مراجع را از لیست زیر وارد کنید:\n{client_list}")
    return RECORD_PAYMENT

def payment_client(update: Update, context: CallbackContext) -> int:
    client_name = update.message.text
    if client_name not in df_clients['client_name'].values:
        update.message.reply_text('مراجع یافت نشد. لطفاً نام صحیح را وارد کنید:')
        return RECORD_PAYMENT

    context.user_data['payment_client'] = client_name
    client = get_client(client_name)
    update.message.reply_text(
        f"مراجع: {client_name}\n"
        f"مبلغ قابل پرداخت: {abs(client['balance'])} {client['currency']}\n"
        "لطفاً مبلغ پرداخت شده را وارد کنید:"
    )
    return PAYMENT_AMOUNT

def payment_amount(update: Update, context: CallbackContext) -> int:
    try:
        amount = float(update.message.text)
        client_name = context.user_data['payment_client']

        # ثبت پرداخت
        global df_payments
        new_payment = {
            'client_name': client_name,
            'payment_date': datetime.now().date(),
            'amount': amount,
            'currency': get_client(client_name)['currency'],
            'method': 'cash',
            'notes': 'پرداخت ثبت شده توسط ربات'
        }

        df_payments = pd.concat([df_payments, pd.DataFrame([new_payment])], ignore_index=True)

        # به‌روزرسانی موجودی مراجع
        update_client(client_name, 
                     payments=get_client(client_name)['payments'] + amount,
                     balance=get_client(client_name)['balance'] + amount)

        update.message.reply_text(
            f"پرداخت {amount} {get_client(client_name)['currency']} برای مراجع {client_name} ثبت شد.\n"
            f"موجودی جدید: {get_client(client_name)['balance']} {get_client(client_name)['currency']}"
        )

        return ConversationHandler.END
    except ValueError:
        update.message.reply_text('لطفاً یک عدد معتبر وارد کنید:')
        return PAYMENT_AMOUNT

def client_report(update: Update, context: CallbackContext) -> None:
    if len(df_clients) == 0:
        update.message.reply_text('هنوز مراجعی ثبت نشده است.')
        return

    client_list = "\n".join(df_clients['client_name'].tolist())
    update.message.reply_text(f"نام مراجع را از لیست زیر وارد کنید:\n{client_list}")
    return REPORT_TYPE

def generate_client_report(update: Update, context: CallbackContext) -> None:
    client_name = update.message.text
    if client_name not in df_clients['client_name'].values:
        update.message.reply_text('مراجع یافت نشد.')
        return

    client = get_client(client_name)
    sessions = df_sessions[df_sessions['client_name'] == client_name]
    payments = df_payments[df_payments['client_name'] == client_name]

    report = (
        f"گزارش مراجع: {client_name}\n"
        f"واحد مالی: {client['currency']}\n"
        f"مبلغ هر جلسه: {client['session_fee']}\n"
        f"تعداد جلسات: {client['sessions_count']}\n"
        f"تعداد کنسلی‌ها: {client['cancellations']}\n"
        f"تعداد جابجایی‌ها: {client['reschedules']}\n"
        f"مجموع پرداختی‌ها: {client['payments']}\n"
        f"وضعیت حساب: {client['balance']} ({'طلبکار' if client['balance'] > 0 else 'بدهکار'})\n"
        f"آخرین جلسه برنامه‌ریزی شده: {to_jalali(client['next_session']).strftime('%Y-%m-%d %H:%M') if pd.notnull(client['next_session']) else 'ندارد'}"
    )

    update.message.reply_text(report)

def financial_report(update: Update, context: CallbackContext) -> None:
    if len(df_payments) == 0:
        update.message.reply_text('هنوز پرداختی ثبت نشده است.')
        return

    keyboard = [
        [InlineKeyboardButton("روزانه", callback_data='daily')],
        [InlineKeyboardButton("هفتگی", callback_data='weekly')],
        [InlineKeyboardButton("ماهانه", callback_data='monthly')],
        [InlineKeyboardButton("سالانه", callback_data='yearly')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text('نوع گزارش مالی را انتخاب کنید:', reply_markup=reply_markup)
    return REPORT_PERIOD

def generate_financial_report(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()

    period = query.data
    now = datetime.now()

    if period == 'daily':
        start_date = now.date()
        title = 'روزانه'
    elif period == 'weekly':
        start_date = (now - timedelta(days=now.weekday())).date()
        title = 'هفتگی'
    elif period == 'monthly':
        start_date = now.replace(day=1).date()
        title = 'ماهانه'
    else:  # yearly
        start_date = now.replace(month=1, day=1).date()
        title = 'سالانه'

    report_data = df_payments[df_payments['payment_date'] >= start_date]

    if report_data.empty:
        query.edit_message_text(f"هیچ پرداختی برای گزارش {title} یافت نشد.")
        return

    total = report_data['amount'].sum()
    count = len(report_data)
    avg = total / count
    by_currency = report_data.groupby('currency')['amount'].sum()

    report = (
        f"گزارش مالی {title}\n"
        f"از تاریخ {to_jalali(start_date).strftime('%Y-%m-%d')} تا کنون\n\n"
        f"تعداد پرداخت‌ها: {count}\n"
        f"مجموع درآمد: {total:.2f}\n"
        f"میانگین پرداخت: {avg:.2f}\n\n"
        "درآمد به تفکیک ارز:\n"
    )

    for currency, amount in by_currency.items():
        report += f"- {currency}: {amount:.2f}\n"

    # ایجاد نمودار
    plt.figure(figsize=(10, 5))
    report_data.groupby('payment_date')['amount'].sum().plot(kind='bar')
    plt.title(f'گزارش درآمد {title}')
    plt.xlabel('تاریخ')
    plt.ylabel('مبلغ')

    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()

    query.message.reply_photo(photo=buf, caption=report)
    query.edit_message_text('گزارش مالی آماده شد.')

def schedule_report(update: Update, context: CallbackContext) -> None:
    now = datetime.now()
    tomorrow = now + timedelta(days=1)

    # جلسات فردا
    tomorrow_sessions = df_sessions[
        (df_sessions['session_date'] == tomorrow.date()) & 
        (df_sessions['status'] == 'scheduled')
    ]

    # زمان‌های خالی (این بخش نیاز به منطق پیچیده‌تری دارد)
    # برای سادگی، فرض می‌کنیم ساعت کاری 9 تا 17 است
    work_hours = [f"{h:02d}:00" for h in range(9, 17)]
    booked_hours = tomorrow_sessions['session_time'].apply(lambda x: x.strftime('%H:%M')).tolist()
    free_hours = [h for h in work_hours if h not in booked_hours]

    report = (
        f"برنامه فردا ({to_jalali(tomorrow).strftime('%Y-%m-%d')}):\n"
        f"تعداد جلسات: {len(tomorrow_sessions)}\n\n"
        "جلسات برنامه‌ریزی شده:\n"
    )

    for _, session in tomorrow_sessions.iterrows():
        report += f"- {session['client_name']} ساعت {session['session_time'].strftime('%H:%M')}\n"

    report += "\nزمان‌های خالی:\n" + "\n".join(f"- {h}" for h in free_hours)

    update.message.reply_text(report)

def cancel(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('عملیات کنسل شد.')
    return ConversationHandler.END

def error_handler(update: Update, context: CallbackContext) -> None:
    logger.error(msg="خطا در هندلر:", exc_info=context.error)
    update.message.reply_text('متاسفانه خطایی رخ داده است. لطفاً دوباره تلاش کنید.')

keep_alive()  # این خط را قبل از main() اضافه کنید
def main() -> None:
    # توکن ربات شما
    TOKEN = '7853586472:AAFV-O9m54jZ3ifiQ187eOT80jE6QxA3yV4'

    try:
        # تست اتصال و راه‌اندازی ربات
        updater = Updater(TOKEN, use_context=True)

        dispatcher = updater.dispatcher

        # هندلرهای گفتگو
        conv_handler_add_client = ConversationHandler(
            entry_points=[CommandHandler('add_client', add_client)],
            states={
                ADD_CLIENT: [MessageHandler(Filters.text & ~Filters.command, add_client_name)],
                ADD_CURRENCY: [CallbackQueryHandler(add_currency)],
                ADD_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, add_amount)],
                ADD_SCHEDULE: [CallbackQueryHandler(add_schedule)],
                ADD_TIME: [MessageHandler(Filters.text & ~Filters.command, add_time)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        conv_handler_payment = ConversationHandler(
            entry_points=[CommandHandler('record_payment', record_payment)],
            states={
                RECORD_PAYMENT: [MessageHandler(Filters.text & ~Filters.command, payment_client)],
                PAYMENT_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, payment_amount)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        conv_handler_client_report = ConversationHandler(
            entry_points=[CommandHandler('client_report', client_report)],
            states={
                REPORT_TYPE: [MessageHandler(Filters.text & ~Filters.command, generate_client_report)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        conv_handler_financial_report = ConversationHandler(
            entry_points=[CommandHandler('financial_report', financial_report)],
            states={
                REPORT_PERIOD: [CallbackQueryHandler(generate_financial_report)],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )

        # ثبت هندلرها
        dispatcher.add_handler(CommandHandler('start', start))
        dispatcher.add_handler(conv_handler_add_client)
        dispatcher.add_handler(conv_handler_payment)
        dispatcher.add_handler(conv_handler_client_report)
        dispatcher.add_handler(conv_handler_financial_report)
        dispatcher.add_handler(CommandHandler('schedule_report', schedule_report))
        dispatcher.add_error_handler(error_handler)

        # شروع ربات
        updater.start_polling()
        print("ربات با موفقیت شروع به کار کرد...")
        updater.idle()

    except Exception as e:
        print(f"خطا در راه‌اندازی ربات: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
