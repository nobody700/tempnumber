


import os 
import sys 
import time 
import base64 
import json 
import logging 
import random 
import asyncio 

import requests 
from Crypto .Cipher import AES 
from Crypto .Util .Padding import unpad 

from telegram import (
Update ,
InlineKeyboardButton ,
InlineKeyboardMarkup ,
constants ,
error as telegram_error ,
)
from telegram .ext import (
Application ,
CommandHandler ,
CallbackQueryHandler ,
ConversationHandler ,
ContextTypes ,
PicklePersistence ,
MessageHandler ,
filters ,
)

import config 

logging .basicConfig (
format ="%(asctime)s - %(name)s - %(levelname)s - %(message)s",level =logging .INFO 
)
logger =logging .getLogger (__name__ )

PERSISTENCE_KEYS =["admin_list","user_request_history","cached_countries"]
global_data ={
"admin_list":[config .DEFAULT_ADMIN_ID ],
"user_request_history":{},
"cached_countries":[],
}


AUTH_KEY =None 


CHOOSE_COUNTRY ,VIEW_NUMBERS ,VIEW_SMS =range (3 )

CB_COUNTRY_PAGE ="cp"
CB_SELECT_COUNTRY ="sc"
CB_NUMBERS_PAGE ="np"
CB_SELECT_NUMBER ="sn"
CB_RANDOM_NUMBER ="rn"
CB_REFRESH_SMS ="rs"
CB_BACK_NUMBERS ="bn"
CB_BACK_COUNTRIES ="bc"
CB_COPY_NUMBER ="copy"
CB_IGNORE ="ignore"


async def auto_refresh_auth_key ():
    """
    Background task to periodically fetch and update the global AUTH_KEY.
    Runs every 2 seconds.
    """
    global AUTH_KEY 
    logger .info ("Starting auth key auto-refresh task...")
    while True :
        try :

            new_key =fetch_authkey ()
            if new_key :

                AUTH_KEY =new_key 



        except Exception as e :

            logger .warning (f"Failed to auto-refresh auth key: {e}")

        await asyncio .sleep (2 )


def fetch_authkey ()->str |None :
    """
    Fetches the encrypted auth key from the API and returns the decrypted key.
    """
    url =config .API_AUTH_URL 
    params ={"action":"get_encrypted_api_key","type":"user"}
    json_data ={"api":"111"}
    try :

        rq =requests .post (url ,params =params ,headers =config .HEADERS ,json =json_data ,timeout =10 )
        rq .raise_for_status ()
        response_data =rq .json ()
        if "api_key"in response_data :
            encrypted_key =response_data ["api_key"]

            return decrypt_key (encrypted_key )
        else :
            logger .error (f"Auth key response missing 'api_key': {response_data}")
            return None 
    except requests .exceptions .RequestException as e :
        logger .error (f"Error fetching auth key: {e}")
        return None 
    except json .JSONDecodeError :
        logger .error ("Failed to decode JSON response for auth key.")
        return None 
    except Exception as e :
        logger .error (f"An unexpected error occurred while fetching auth key: {e}")
        return None 


def decrypt_key (encrypted_str :str )->str |None :
    """
    Decrypts the base64 encoded AES encrypted key.
    """
    key =b"9e8986a75ffa32aa187b7f34394c70ea"
    try :

        decode =base64 .b64decode (encrypted_str )

        iv =decode [:16 ]
        encrypted_data =decode [16 :]

        cipher =AES .new (key ,AES .MODE_CBC ,iv )

        decrypted_data =unpad (cipher .decrypt (encrypted_data ),AES .block_size )

        return decrypted_data .decode ('utf-8')
    except Exception as e :

        logger .error (f"Error decrypting API key: {e}")
        return None 


def get_auth_key ()->str |None :
    """
    Returns the current value of the global AUTH_KEY.
    Relies on the background task `auto_refresh_auth_key` to keep it updated.
    """
    global AUTH_KEY 


    if AUTH_KEY is None :


        logger .warning ("Auth key is None when requested by get_auth_key. Background task may not have set it yet or encountered an error.")
    return AUTH_KEY 



def fetch_countries_data ()->list :
    """
    Fetches the list of available countries from the API.
    Caches the result globally.
    """
    global global_data 
    if global_data ["cached_countries"]:
        logger .info ("Using cached countries.")
        return global_data ["cached_countries"]

    url =config .API_COUNTRIES_URL 
    params ={"action":"country"}
    try :
        logger .info ("Fetching countries...")
        rq =requests .post (url ,params =params ,headers =config .HEADERS ,timeout =15 )
        rq .raise_for_status ()
        data =rq .json ()
        if "records"in data and isinstance (data ["records"],list ):
             logger .info (f"Fetched {len(data['records'])} countries.")
             global_data ["cached_countries"]=data ["records"]
             return data ["records"]
        else :
            logger .error (f"API response for countries missing 'records' or not a list: {data}")
            return []
    except requests .exceptions .RequestException as e :
        logger .error (f"Error fetching countries: {e}")
        return []
    except json .JSONDecodeError :
         logger .error ("Failed to decode JSON response for countries.")
         return []
    except Exception as e :
         logger .error (f"An unexpected error occurred while fetching countries: {e}")
         return []

def fetch_numbers_data (country :str ,page :int )->dict :
    """
    Fetches available numbers for a given country and page from the API.
    Uses the global AUTH_KEY. Includes retry logic for potential expired tokens.
    """
    auth_key =get_auth_key ()
    if not auth_key :
        logger .warning ("Cannot fetch numbers: Auth key not available.")
        return {"Available_numbers":[],"Total_Pages":0 }

    url =config .API_NUMBERS_URL 
    params ={"action":"GetFreeNumbers","type":"user"}
    headers =config .HEADERS .copy ()
    headers ["authorization"]="Bearer "+auth_key 
    json_data ={
    "country_name":country ,
    "limit":config .NUMBERS_PER_PAGE ,
    "page":page 
    }

    try :
        logger .info (f"Fetching numbers for {country}, page {page}...")
        rq =requests .post (url ,params =params ,headers =headers ,json =json_data ,timeout =15 )
        rq .raise_for_status ()
        data =rq .json ()
        if "Available_numbers"in data and "Total_Pages"in data :
            logger .info (f"Fetched {len(data['Available_numbers'])} numbers for {country}, page {page}. Total pages: {data.get('Total_Pages', 'N/A')}")
            return data 
        else :
             logger .warning (f"API response for numbers in {country} (page {page}) did not contain expected keys: {data}")
             return {"Available_numbers":[],"Total_Pages":0 }
    except requests .exceptions .RequestException as e :
        logger .error (f"Error fetching numbers for {country} (page {page}): {e}")

        if isinstance (e ,requests .exceptions .HTTPError )and e .response .status_code in (400 ,401 ):
             logger .warning ("Potential token expiration during number fetch. Retrying once.")
             auth_key_retry =get_auth_key ()
             if auth_key_retry and auth_key_retry !=auth_key :
                 headers ["authorization"]="Bearer "+auth_key_retry 
                 try :
                     rq =requests .post (url ,params =params ,headers =headers ,json =json_data ,timeout =15 )
                     rq .raise_for_status ()
                     data =rq .json ()
                     if "Available_numbers"in data and "Total_Pages"in data :
                         logger .info (f"Retry successful for {country}, page {page}.")
                         return data 
                     else :
                         logger .warning (f"Retry response for numbers in {country} (page {page}) did not contain expected keys: {data}")
                 except Exception as retry_err :
                     logger .error (f"Retry failed for {country}, page {page}: {retry_err}")
        return {"Available_numbers":[],"Total_Pages":0 }
    except json .JSONDecodeError :
         logger .error (f"Failed to decode JSON response for numbers in {country} (page {page}).")
         return {"Available_numbers":[],"Total_Pages":0 }
    except Exception as e :
         logger .error (f"An unexpected error occurred while fetching numbers: {e}")
         return {"Available_numbers":[],"Total_Pages":0 }


def fetch_sms_data (number :str )->list :
    """
    Fetches SMS messages for a given number from the API.
    Uses the global AUTH_KEY.
    """
    auth_key =get_auth_key ()
    if not auth_key :
        logger .warning ("Cannot fetch SMS: Auth key not available.")
        return []

    url =config .API_SMS_URL 
    json_data ={"no":number ,"page":"1"}
    headers =config .HEADERS .copy ()
    headers ["authorization"]="Bearer "+auth_key 

    try :
        logger .info (f"Fetching SMS for number {number}...")
        rq =requests .post (url ,headers =headers ,json =json_data ,timeout =20 )
        rq .raise_for_status ()
        data =rq .json ()

        if "messages"in data and isinstance (data ["messages"],list ):
            logger .info (f"Fetched {len(data['messages'])} messages for {number}.")
            return data ["messages"]
        else :
            logger .warning (f"API response for SMS for number {number} did not contain 'messages' key or not a list: {data}")
            return []
    except requests .exceptions .RequestException as e :
        logger .error (f"Error fetching SMS for number {number}: {e}")
        return []
    except json .JSONDecodeError :
        logger .error (f"Failed to decode JSON response for SMS for number {number}. Invalid JSON received.")
        return []
    except Exception as e :
        logger .error (f"An unexpected error occurred while fetching SMS for number {number}: {e}")
        return []


def is_rate_limited (user_id :int )->tuple [bool ,int ]:
    """
    Checks if a user is rate-limited based on their request history.
    Returns True and remaining time if limited, False and 0 otherwise.
    """
    history =global_data ["user_request_history"].get (user_id ,[])

    now =time .time ()

    history =[ts for ts in history if now -ts <config .RATE_LIMIT_PERIOD_SECONDS ]
    global_data ["user_request_history"][user_id ]=history 

    if len (history )<config .NUMBER_LIMIT_PER_PERIOD :
        return False ,0 


    oldest_request_time =history [0 ]
    time_elapsed_since_oldest =now -oldest_request_time 
    time_needed_to_wait =config .RATE_LIMIT_PERIOD_SECONDS -time_elapsed_since_oldest 
    return True ,int (max (0 ,time_needed_to_wait ))

def record_request (user_id :int )->None :
    """
    Records a number request for a user to track rate limits.
    Cleans up old history entries.
    """
    if user_id not in global_data ["user_request_history"]:
        global_data ["user_request_history"][user_id ]=[]


    is_rate_limited (user_id )

    global_data ["user_request_history"][user_id ].append (time .time ())
    logger .info (f"User {user_id} requested a number. History count: {len(global_data['user_request_history'][user_id])}")


def is_admin (user_id :int )->bool :
    """
    Checks if a user ID is in the admin list.
    """
    return user_id in global_data ["admin_list"]


def build_country_keyboard (countries :list ,current_page :int )->InlineKeyboardMarkup :
    """
    Builds the inline keyboard for country selection with pagination.
    """
    keyboard =[]

    start_index =(current_page -1 )*config .COUNTRIES_PER_PAGE 
    end_index =start_index +config .COUNTRIES_PER_PAGE 
    countries_on_page =countries [start_index :end_index ]

    row =[]
    for country in countries_on_page :
        country_name =country .get ('Country_Name','Unknown').split ('(')[0 ].strip ()
        country_code =country .get ('country_code','N/A')
        flag_emoji =country .get ('emoji','❓')

        button_text =f"{flag_emoji} {country_name}"
        callback_data =f"{CB_SELECT_COUNTRY}:{country_code}"
        row .append (InlineKeyboardButton (button_text ,callback_data =callback_data ))

        if len (row )==2 :
            keyboard .append (row )
            row =[]

    if row :
        keyboard .append (row )


    total_pages =(len (countries )+config .COUNTRIES_PER_PAGE -1 )//config .COUNTRIES_PER_PAGE 
    nav_row =[]
    if current_page >1 :
        nav_row .append (InlineKeyboardButton ("⬅️ Prev",callback_data =f"{CB_COUNTRY_PAGE}:{current_page - 1}"))
    nav_row .append (InlineKeyboardButton (f"Page {current_page}/{total_pages}",callback_data =CB_IGNORE ))
    if current_page <total_pages :
        nav_row .append (InlineKeyboardButton ("Next ➡️",callback_data =f"{CB_COUNTRY_PAGE}:{current_page + 1}"))
    if nav_row :
        keyboard .append (nav_row )


    keyboard .append ([InlineKeyboardButton ("✖️ Cancel",callback_data =f"{CB_IGNORE}")])

    return InlineKeyboardMarkup (keyboard )

def build_number_keyboard (numbers :list ,country_code :str ,current_page :int ,total_pages :int )->InlineKeyboardMarkup :
    """
    Builds the inline keyboard for number selection with pagination and random option.
    """
    keyboard =[]

    numbers_on_page =numbers 

    for number_data in numbers_on_page :
        e164_number =number_data .get ('E.164','N/A')
        last_seen =number_data .get ('time','Unknown Time')
        button_text =f"📱 {e164_number} (Last SMS: {last_seen})"
        callback_data =f"{CB_SELECT_NUMBER}:{e164_number}"

        if len (callback_data .encode ('utf-8'))>64 :
             logger .warning (f"Callback data too long for number {e164_number}. Skipping button.")
             continue 

        keyboard .append ([InlineKeyboardButton (button_text ,callback_data =callback_data )])


    nav_row_top =[InlineKeyboardButton ("🎲 Random Number",callback_data =f"{CB_RANDOM_NUMBER}:{country_code}")]
    keyboard .append (nav_row_top )


    nav_row_bottom =[]
    if current_page >1 :
        nav_row_bottom .append (InlineKeyboardButton ("⬅️ Prev",callback_data =f"{CB_NUMBERS_PAGE}:{country_code}:{current_page - 1}"))
    nav_row_bottom .append (InlineKeyboardButton (f"Page {current_page}/{total_pages}",callback_data =CB_IGNORE ))
    if current_page <total_pages :
        nav_row_bottom .append (InlineKeyboardButton ("Next ➡️",callback_data =f"{CB_NUMBERS_PAGE}:{country_code}:{current_page + 1}"))
    if nav_row_bottom :
        keyboard .append (nav_row_bottom )


    keyboard .append ([InlineKeyboardButton ("🔙 Back to Countries",callback_data =f"{CB_BACK_COUNTRIES}:1")])

    return InlineKeyboardMarkup (keyboard )


def build_sms_keyboard (number_e164 :str )->InlineKeyboardMarkup :
    """
    Builds the inline keyboard for the SMS view (refresh, copy, back).
    """
    keyboard =[
    [
    InlineKeyboardButton ("🔄 Refresh Messages",callback_data =f"{CB_REFRESH_SMS}:{number_e164}"),
    ],
    [
    InlineKeyboardButton ("📋 Copy Number",callback_data =f"{CB_COPY_NUMBER}:{number_e164}"),
    ],
    [
    InlineKeyboardButton ("🔙 Back to Numbers",callback_data =f"{CB_BACK_NUMBERS}:dummy")
    ]
    ]
    return InlineKeyboardMarkup (keyboard )


def format_sms_messages (messages :list )->str :
    """
    Formats a list of SMS messages into a readable string.
    """
    if not messages :
        return "No messages found yet for this number."

    try :

        messages .sort (key =lambda x :x .get ('message_time',''))
    except Exception :
        logger .warning ("Could not sort messages by time.")

    text ="<b>✉️ Messages:</b>\n\n"
    for msg in messages :
        sender =msg .get ('FromNumber','Unknown Sender')
        body =msg .get ('Messagebody','No content')
        time_str =msg .get ('message_time','Unknown Time')


        try :
            if isinstance (body ,str ):
                display_body =body .strip ()
            elif isinstance (body ,bytes ):
                display_body =body .decode ('utf-8',errors ='replace').strip ()
            else :
                display_body =str (body ).strip ()
        except Exception :
            display_body ="Error displaying message content"


        text +=f"👤 <b>From:</b> <code>{sender}</code>\n"
        text +=f"💬 <b>Message:</b> <code>{display_body}</code>\n"
        text +=f"⏰ <i>Time:</i> {time_str}\n"
        text +="──────────────\n"

    return text 




async def start (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Starts the conversation and shows the country selection."""
    user =update .effective_user 
    logger .info (f"User {user.id} started conversation.")


    if not global_data ["cached_countries"]:
        await update .message .reply_text ("Fetching available countries, please wait...")
        countries =fetch_countries_data ()
        if not countries :
            await update .message .reply_text (
            "⚠️ Could not fetch countries. Please try again later."
            )
            return ConversationHandler .END 

    countries =global_data ["cached_countries"]
    if not countries :
         await update .message .reply_text (
         "⚠️ No countries available at this time. Please try again later."
         )
         return ConversationHandler .END 


    context .user_data ["country_list"]=countries 
    context .user_data ["country_page"]=1 


    keyboard =build_country_keyboard (countries ,1 )

    await update .message .reply_text (
    f"👋 Hello {user.first_name}!\nSelect a country to get a temporary number:",
    reply_markup =keyboard ,
    parse_mode =constants .ParseMode .HTML 
    )

    return CHOOSE_COUNTRY 


async def navigate_countries (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles pagination for country selection."""
    query =update .callback_query 
    await query .answer ()


    page =int (query .data .split (":")[1 ])
    countries =context .user_data .get ("country_list")

    if not countries :
        await query .edit_message_text ("Error: Country list not found.")
        return ConversationHandler .END 


    context .user_data ["country_page"]=page 

    keyboard =build_country_keyboard (countries ,page )

    try :
        await query .edit_message_text (
        "🌎 Select a country:",
        reply_markup =keyboard ,
        parse_mode =constants .ParseMode .HTML 
        )
    except telegram_error .BadRequest as e :
        logger .warning (f"Failed to edit message in navigate_countries: {e}")

        pass 

    return CHOOSE_COUNTRY 


async def select_country (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles country selection and fetches numbers."""
    query =update .callback_query 
    await query .answer ("Fetching numbers...")


    country_code =query .data .split (":")[1 ]
    countries =context .user_data .get ("country_list")

    selected_country =next ((c for c in countries if c .get ('country_code')==country_code ),None )

    if not selected_country :
        await query .edit_message_text ("Error: Selected country not found.")
        return ConversationHandler .END 

    country_name =selected_country .get ('Country_Name','Unknown Country')

    user_id =query .from_user .id 

    is_limited ,wait_time =is_rate_limited (user_id )

    if is_limited :
        await query .edit_message_text (
        f"🚫 Rate Limit Exceeded! You can only request {config.NUMBER_LIMIT_PER_PERIOD} numbers per {config.RATE_LIMIT_PERIOD_SECONDS // 3600} hours.\n"
        f"Please wait {wait_time // 60} minutes and {wait_time % 60} seconds before requesting another number."
        )
        return ConversationHandler .END 


    loading_message =await query .edit_message_text (f"⏳ Fetching numbers for {country_name}...",reply_markup =None )


    numbers_data =fetch_numbers_data (country_name ,1 )
    numbers_list =numbers_data .get ("Available_numbers",[])
    total_pages =numbers_data .get ("Total_Pages",0 )

    if not numbers_list :

        await loading_message .edit_text (
        f"😞 No numbers available for {country_name} at this time.\n"
        f"Please select a different country."
        )
        countries =global_data ["cached_countries"]
        if countries :
            keyboard =build_country_keyboard (countries ,1 )
            await loading_message .reply_text ("🌎 Select another country:",reply_markup =keyboard ,parse_mode =constants .ParseMode .HTML )
            return CHOOSE_COUNTRY 
        else :
             return ConversationHandler .END 


    context .user_data ["current_country_code"]=country_code 
    context .user_data ["current_country_name"]=country_name 
    context .user_data ["number_list"]=numbers_list 
    context .user_data ["number_page"]=1 
    context .user_data ["total_number_pages"]=total_pages 


    keyboard =build_number_keyboard (
    numbers_list ,country_code ,1 ,total_pages 
    )

    await loading_message .edit_text (
    f"📱 Available numbers for {country_name}:",
    reply_markup =keyboard ,
    parse_mode =constants .ParseMode .HTML 
    )

    return VIEW_NUMBERS 


async def navigate_numbers (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles pagination for number selection."""
    query =update .callback_query 
    await query .answer ("Loading numbers...")


    parts =query .data .split (":")
    country_code =parts [1 ]
    page =int (parts [2 ])

    country_name =context .user_data .get ("current_country_name")
    if not country_name :
         await query .edit_message_text ("Error: Country context lost. Please start again with /start.")
         return ConversationHandler .END 


    loading_message =await query .edit_message_text (f"⏳ Fetching numbers for {country_name}, page {page}...",reply_markup =None )


    numbers_data =fetch_numbers_data (country_name ,page )
    numbers_list =numbers_data .get ("Available_numbers",[])
    total_pages =numbers_data .get ("Total_Pages",0 )

    if not numbers_list :

        await loading_message .edit_text (
        f"😞 No numbers found on page {page} for {country_name}.\n"
        f"Please try going back or selecting a different country."
        )
        previous_page =context .user_data .get ("number_page",1 )
        if previous_page !=page :
             numbers_data_prev =fetch_numbers_data (country_name ,previous_page )
             numbers_list_prev =numbers_data_prev .get ("Available_numbers",[])
             total_pages_prev =numbers_data_prev_data .get ("Total_Pages",0 )
             if numbers_list_prev :
                 keyboard =build_number_keyboard (numbers_list_prev ,country_code ,previous_page ,total_pages_prev )
                 await loading_message .reply_text (f"📱 Showing numbers for {country_name}, page {previous_page}:",reply_markup =keyboard ,parse_mode =constants .ParseMode .HTML )
                 context .user_data ["number_page"]=previous_page 
                 context .user_data ["number_list"]=numbers_list_prev 
                 context .user_data ["total_number_pages"]=total_pages_prev 
                 return VIEW_NUMBERS 


        keyboard =InlineKeyboardMarkup ([[InlineKeyboardButton ("🔙 Back to Countries",callback_data =f"{CB_BACK_COUNTRIES}:1")]])
        await loading_message .reply_text ("Navigation failed. Please try again or go back.",reply_markup =keyboard )
        return VIEW_NUMBERS 


    context .user_data ["number_page"]=page 
    context .user_data ["number_list"]=numbers_list 
    context .user_data ["total_number_pages"]=total_pages 


    keyboard =build_number_keyboard (
    numbers_list ,country_code ,page ,total_pages 
    )

    try :
         await loading_message .edit_text (
         f"📱 Available numbers for {country_name} (Page {page}/{total_pages}):",
         reply_markup =keyboard ,
         parse_mode =constants .ParseMode .HTML 
         )
    except telegram_error .BadRequest as e :
        logger .warning (f"Failed to edit message in navigate_numbers: {e}")
        pass 

    return VIEW_NUMBERS 


async def select_number (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles number selection and fetches SMS messages."""
    query =update .callback_query 
    await query .answer ("Fetching SMS...")


    number_e164 =query .data .split (":")[1 ]
    user_id =query .from_user .id 


    record_request (user_id )


    loading_message =await query .edit_message_text (f"⏳ Fetching messages for {number_e164}...",reply_markup =None )


    sms_list =fetch_sms_data (number_e164 )


    message_text =f"📞 Selected Number: <code>{number_e164}</code>\n\n"+format_sms_messages (sms_list )
    keyboard =build_sms_keyboard (number_e164 )


    context .user_data ["selected_number"]=number_e164 
    context .user_data ["last_sms_refresh_time"]=time .time ()


    await loading_message .edit_text (
    message_text ,
    reply_markup =keyboard ,
    parse_mode ="HTML"
    )

    return VIEW_SMS 


async def select_random_number (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles random number selection for the current country."""
    query =update .callback_query 
    await query .answer ("Selecting random number...")


    country_code =query .data .split (":")[1 ]
    user_id =query .from_user .id 


    is_limited ,wait_time =is_rate_limited (user_id )
    if is_limited :
        await query .edit_message_text (
        f"🚫 Rate Limit Exceeded! You can only request {config.NUMBER_LIMIT_PER_PERIOD} numbers per {config.RATE_LIMIT_PERIOD_SECONDS // 3600} hours.\n"
        f"Please wait {wait_time // 60} minutes and {wait_time % 60} seconds before requesting another number."
        )
        return ConversationHandler .END 

    country_name =context .user_data .get ("current_country_name")
    if not country_name :
         await query .edit_message_text ("Error: Country context lost for random selection. Please start again with /start.")
         return ConversationHandler .END 


    loading_message =await query .edit_message_text (f"🎲 Fetching *all* numbers for {country_name} to pick randomly (this might take a moment)...",parse_mode ="HTML")


    all_numbers =[]
    page =1 

    MAX_NUMBERS_FOR_RANDOM =500 
    while len (all_numbers )<MAX_NUMBERS_FOR_RANDOM :
         numbers_data =fetch_numbers_data (country_name ,page )
         numbers_list =numbers_data .get ("Available_numbers",[])
         if not numbers_list :
             if page ==1 :

                  await loading_message .edit_text (f"😞 No numbers available for {country_name} to pick randomly from.")

                  countries =global_data ["cached_countries"]
                  if countries :
                       keyboard =build_country_keyboard (countries ,1 )
                       await loading_message .reply_text ("🌎 Select another country:",reply_markup =keyboard ,parse_mode =constants .ParseMode .HTML )
                       return CHOOSE_COUNTRY 
                  else :
                       return ConversationHandler .END 
             else :

                  break 
         all_numbers .extend (numbers_list )
         total_pages_advertised =numbers_data .get ("Total_Pages",page )
         page +=1 
         if page >total_pages_advertised :
              logger .info (f"Finished fetching all {total_pages_advertised} pages for random selection.")
              break 
         if len (all_numbers )>=MAX_NUMBERS_FOR_RANDOM :
             logger .warning (f"Capped random number fetching at {MAX_NUMBERS_FOR_RANDOM} numbers for {country_name}.")
             break 


    if not all_numbers :

         await loading_message .edit_text (f"😞 No numbers found for {country_name} after fetching attempts.")

         countries =global_data ["cached_countries"]
         if countries :
              keyboard =build_country_keyboard (countries ,1 )
              await loading_message .reply_text ("🌎 Select a country:",reply_markup =keyboard ,parse_mode =constants .ParseMode .HTML )
              return CHOOSE_COUNTRY 
         else :
              return ConversationHandler .END 


    selected_dict =random .choice (all_numbers )
    selected_number_e164 =selected_dict .get ("E.164")

    if not selected_number_e164 :

         await loading_message .edit_text ("Error picking a random number. Please try selecting from the list.")

         current_page =context .user_data .get ("number_page",1 )
         country_code =context .user_data .get ("current_country_code")
         numbers_list_page =context .user_data .get ("number_list",[])
         total_pages =context .user_data .get ("total_number_pages",1 )
         if numbers_list_page and country_code :
             keyboard =build_number_keyboard (numbers_list_page ,country_code ,current_page ,total_pages )
             await loading_message .reply_text (f"📱 Available numbers for {country_name} (Page {current_page}/{total_pages}):",reply_markup =keyboard ,parse_mode =constants .ParseMode .HTML )
             return VIEW_NUMBERS 
         else :

              countries =global_data ["cached_countries"]
              if countries :
                   keyboard =build_country_keyboard (countries ,1 )
                   await loading_message .reply_text ("🌎 Select a country:",reply_markup =keyboard ,parse_mode =constants .ParseMode .HTML )
                   return CHOOSE_COUNTRY 
              else :
                   return ConversationHandler .END 


    record_request (user_id )


    await loading_message .edit_text (f"⏳ Fetching messages for random number: {selected_number_e164}...",reply_markup =None )

    sms_list =fetch_sms_data (selected_number_e164 )


    message_text =f"📞 Selected Random Number: `{selected_number_e164}`\n\n"+format_sms_messages (sms_list )
    keyboard =build_sms_keyboard (selected_number_e164 )


    context .user_data ["selected_number"]=selected_number_e164 
    context .user_data ["last_sms_refresh_time"]=time .time ()


    await loading_message .edit_text (
    message_text ,
    reply_markup =keyboard ,
    parse_mode ="HTML"
    )

    return VIEW_SMS 


async def refresh_sms (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles refreshing SMS messages for the selected number."""
    query =update .callback_query 

    number_e164 =query .data .split (":")[1 ]
    user_id =query .from_user .id 


    last_refresh_time =context .user_data .get ("last_sms_refresh_time",0 )
    now =time .time ()
    if now -last_refresh_time <config .REFRESH_WAIT_SECONDS :
        remaining_time =int (config .REFRESH_WAIT_SECONDS -(now -last_refresh_time ))
        await query .answer (f"Please wait {remaining_time}s before refreshing again.",show_alert =True )
        return VIEW_SMS 

    await query .answer ("Refreshing messages...")


    loading_message_text =f"🔄 Refreshing messages for `{number_e164}`..."
    keyboard =build_sms_keyboard (number_e164 )

    try :
        await query .edit_message_text (
        loading_message_text ,
        reply_markup =keyboard ,
        parse_mode ="HTML"
        )
    except telegram_error .BadRequest as e :
        logger .warning (f"Could not edit message to show loading: {e}")
        pass 


    sms_list =fetch_sms_data (number_e164 )


    message_text =f"📞 Selected Number: `{number_e164}`\n\n"+format_sms_messages (sms_list )


    context .user_data ["last_sms_refresh_time"]=time .time ()


    try :
        await query .edit_message_text (
        message_text ,
        reply_markup =keyboard ,
        parse_mode ="HTML"
        )
    except telegram_error .BadRequest as e :
         logger .info (f"SMS message content not changed for {number_e164}. Edit failed: {e}")
         pass 

    return VIEW_SMS 

async def copy_number (update :Update ,context :ContextTypes .DEFAULT_TYPE )->None :
    """Handles the copy number action."""
    query =update .callback_query 

    number_e164 =query .data .split (":")[1 ]

    await query .answer ("Number copied! (Check the new message)")


    copy_message_text =f"Here is the number again for easy copying:\n`{number_e164}`"

    try :
        await context .bot .send_message (
        chat_id =update .effective_chat .id ,
        text =copy_message_text ,
        parse_mode ="HTML"
        )
    except Exception as e :
        logger .error (f"Error sending copy message: {e}")
        await query .answer ("Failed to send copiable number message. You can still copy it from the message above.",show_alert =True )


async def back_to_numbers (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles going back from SMS view to number list view."""
    query =update .callback_query 
    await query .answer ()


    country_code =context .user_data .get ("current_country_code")
    country_name =context .user_data .get ("current_country_name")
    current_page =context .user_data .get ("number_page",1 )
    numbers_list =context .user_data .get ("number_list",[])
    total_pages =context .user_data .get ("total_number_pages",1 )


    if not country_code or not country_name or not numbers_list :
        await query .edit_message_text ("Context lost. Returning to country selection.")

        countries =global_data ["cached_countries"]
        if countries :
             keyboard =build_country_keyboard (countries ,1 )
             await query .reply_text ("🌎 Select a country:",reply_markup =keyboard ,parse_mode =constants .ParseMode .HTML )
             return CHOOSE_COUNTRY 
        else :
             await query .edit_message_text ("No countries available. Exiting.")
             return ConversationHandler .END 



    keyboard =build_number_keyboard (numbers_list ,country_code ,current_page ,total_pages )

    try :
        await query .edit_message_text (
        f"📱 Available numbers for {country_name} (Page {current_page}/{total_pages}):",
        reply_markup =keyboard ,
        parse_mode =constants .ParseMode .HTML 
        )
    except telegram_error .BadRequest as e :
        logger .warning (f"Failed to edit message in back_to_numbers: {e}")

        await query .message .reply_text (
        f"📱 Available numbers for {country_name} (Page {current_page}/{total_pages}):",
        reply_markup =keyboard ,
        parse_mode =constants .ParseMode .HTML 
        )


    context .user_data .pop ("selected_number",None )
    context .user_data .pop ("last_sms_refresh_time",None )

    return VIEW_NUMBERS 


async def back_to_countries (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Handles going back from number list view to country selection view."""
    query =update .callback_query 
    await query .answer ()


    last_country_page =context .user_data .get ("country_page",1 )

    countries =context .user_data .get ("country_list")
    if not countries :
         await query .edit_message_text ("Error: Country list not found. Please start again with /start.")
         return ConversationHandler .END 


    keyboard =build_country_keyboard (countries ,last_country_page )

    try :
         await query .edit_message_text (
         "🌎 Select a country:",
         reply_markup =keyboard ,
         parse_mode =constants .ParseMode .HTML 
         )
    except telegram_error .BadRequest as e :
         logger .warning (f"Failed to edit message in back_to_countries: {e}")

         await query .message .reply_text (
         "🌎 Select a country:",
         reply_markup =keyboard ,
         parse_mode =constants .ParseMode .HTML 
         )


    context .user_data .pop ("current_country_code",None )
    context .user_data .pop ("current_country_name",None )
    context .user_data .pop ("number_list",None )
    context .user_data .pop ("number_page",None )
    context .user_data .pop ("total_number_pages",None )

    return CHOOSE_COUNTRY 


async def cancel_conversation (update :Update ,context :ContextTypes .DEFAULT_TYPE )->int :
    """Cancels the current conversation."""
    user =update .effective_user 
    logger .info (f"User {user.id} canceled the conversation.")


    if update .callback_query :
         await update .callback_query .answer ("Operation canceled.")
         try :

              await update .callback_query .edit_message_text ("✖️ Operation canceled.")
         except telegram_error .BadRequest :
              pass 
    else :

         await update .message .reply_text ("✖️ Operation canceled.")


    context .user_data .clear ()

    return ConversationHandler .END 




async def admin_command (update :Update ,context :ContextTypes .DEFAULT_TYPE )->None :
    """Shows admin panel help."""
    user_id =update .effective_user .id 
    if not is_admin (user_id ):
        await update .message .reply_text ("🚫 You are not authorized to use this command.")
        return 

    admin_text =(
    "⚙️ *Admin Panel*\n\n"
    "Available commands:\n"
    "`/mc <user_id>` - Add user_id as admin\n"
    "`/rm <user_id>` - Remove user_id from admins"
    )
    await update .message .reply_text (admin_text ,parse_mode ="HTML")


async def add_admin_command (update :Update ,context :ContextTypes .DEFAULT_TYPE )->None :
    """Adds a user ID to the admin list."""
    user_id =update .effective_user .id 
    if not is_admin (user_id ):
        await update .message .reply_text ("🚫 You are not authorized to use this command.")
        return 

    if not context .args :
        await update .message .reply_text ("Usage: `/mc <user_id>`",parse_mode ="HTML")
        return 

    try :

        new_admin_id =int (context .args [0 ])
        if new_admin_id <=0 :
             raise ValueError ("User ID must be positive.")
    except ValueError :
        await update .message .reply_text ("❌ Invalid user ID provided. Please use a numeric ID.")
        return 


    if new_admin_id in global_data ["admin_list"]:
        await update .message .reply_text (f"✅ User ID `{new_admin_id}` is already an admin.",parse_mode ="HTML")
        return 


    global_data ["admin_list"].append (new_admin_id )

    await update .message .reply_text (f"🎉 User ID `{new_admin_id}` has been added as an admin.",parse_mode ="HTML")
    logger .info (f"Admin {user_id} added new admin: {new_admin_id}")


    try :
        await context .bot .send_message (new_admin_id ,"You have been added as an admin for the Temp SMS Bot!")
    except telegram_error .Forbidden :
        logger .warning (f"Could not notify new admin {new_admin_id}: Bot blocked by user.")
    except Exception as e :
        logger .error (f"Error notifying new admin {new_admin_id}: {e}")


async def remove_admin_command (update :Update ,context :ContextTypes .DEFAULT_TYPE )->None :
    """Removes a user ID from the admin list."""
    user_id =update .effective_user .id 
    if not is_admin (user_id ):
        await update .message .reply_text ("🚫 You are not authorized to use this command.")
        return 

    if not context .args :
        await update .message .reply_text ("Usage: `/rm <user_id>`",parse_mode ="HTML")
        return 

    try :

        old_admin_id =int (context .args [0 ])
        if old_admin_id <=0 :
             raise ValueError ("User ID must be positive.")
    except ValueError :
        await update .message .reply_text ("❌ Invalid user ID provided. Please use a numeric ID.")
        return 


    if old_admin_id ==config .DEFAULT_ADMIN_ID :
        await update .message .reply_text ("❌ The default admin cannot be removed.",parse_mode ="HTML")
        return 


    if old_admin_id not in global_data ["admin_list"]:
        await update .message .reply_text (f"🤔 User ID `{old_admin_id}` is not currently an admin.",parse_mode ="HTML")
        return 

    try :

        global_data ["admin_list"].remove (old_admin_id )

        await update .message .reply_text (f"🗑️ User ID `{old_admin_id}` has been removed from admins.",parse_mode ="HTML")
        logger .info (f"Admin {user_id} removed admin: {old_admin_id}")

        try :
            await context .bot .send_message (old_admin_id ,"You have been removed as an admin for the Temp SMS Bot.")
        except telegram_error .Forbidden :
            logger .warning (f"Could not notify removed admin {old_admin_id}: Bot blocked by user.")
        except Exception as e :
            logger .error (f"Error notifying removed admin {old_admin_id}: {e}")

    except ValueError :
         await update .message .reply_text (f"Error removing user ID `{old_admin_id}`.",parse_mode ="HTML")



async def main ()->None :
    """Starts the bot and handles setup."""
    logger .info ("Starting bot...")



    global AUTH_KEY 
    AUTH_KEY =fetch_authkey ()
    if not AUTH_KEY :
        logger .error ("Initial auth key fetch failed. Bot may not function correctly until background task succeeds.")

    asyncio .create_task (auto_refresh_auth_key ())



    fetch_countries_data ()


    persistence =PicklePersistence (filepath =config .PERSISTENCE_FILE )

    try :

        loaded_data =await persistence .get_bot_data ()
        if loaded_data :
            for key in PERSISTENCE_KEYS :
                if key in loaded_data :
                    global_data [key ]=loaded_data [key ]
            logger .info (f"Loaded persistence data for keys: {PERSISTENCE_KEYS}")
            logger .info (f"Admin list: {global_data['admin_list']}")
            logger .info (f"Rate limit history users: {list(global_data['user_request_history'].keys())}")
        else :
             logger .info ("No persistence data found, starting fresh.")
    except Exception as e :
        logger .error (f"Error loading persistence data: {e}")
        logger .warning ("Starting with default/empty persistence data.")


    if config .DEFAULT_ADMIN_ID not in global_data ["admin_list"]:
         global_data ["admin_list"].append (config .DEFAULT_ADMIN_ID )
         logger .info (f"Added default admin {config.DEFAULT_ADMIN_ID} to admin list.")



    application =Application .builder ().token (config .BOT_TOKEN ).persistence (persistence ).read_timeout (10 ).write_timeout (10 ).build ()


    application .bot_data =global_data 


    conv_handler =ConversationHandler (
    entry_points =[CommandHandler ("start",start )],
    states ={
    CHOOSE_COUNTRY :[
    CallbackQueryHandler (navigate_countries ,pattern =f"^{CB_COUNTRY_PAGE}:"),
    CallbackQueryHandler (select_country ,pattern =f"^{CB_SELECT_COUNTRY}:"),
    CallbackQueryHandler (cancel_conversation ,pattern =f"^{CB_IGNORE}"),
    ],
    VIEW_NUMBERS :[
    CallbackQueryHandler (navigate_numbers ,pattern =f"^{CB_NUMBERS_PAGE}:"),
    CallbackQueryHandler (select_number ,pattern =f"^{CB_SELECT_NUMBER}:"),
    CallbackQueryHandler (select_random_number ,pattern =f"^{CB_RANDOM_NUMBER}:"),
    CallbackQueryHandler (back_to_countries ,pattern =f"^{CB_BACK_COUNTRIES}:"),
    CallbackQueryHandler (cancel_conversation ,pattern =f"^{CB_IGNORE}"),
    ],
    VIEW_SMS :[
    CallbackQueryHandler (refresh_sms ,pattern =f"^{CB_REFRESH_SMS}:"),
    CallbackQueryHandler (copy_number ,pattern =f"^{CB_COPY_NUMBER}:"),
    CallbackQueryHandler (back_to_numbers ,pattern =f"^{CB_BACK_NUMBERS}:"),
    CallbackQueryHandler (cancel_conversation ,pattern =f"^{CB_IGNORE}"),
    ],
    },
    fallbacks =[
    CommandHandler ("start",start ),
    CommandHandler ("cancel",cancel_conversation ),
    MessageHandler (filters .TEXT &~filters .COMMAND ,cancel_conversation )
    ],
    name ="temp_sms_conversation",
    persistent =True ,
    )


    application .add_handler (conv_handler )


    application .add_handler (CommandHandler ("admin",admin_command ))
    application .add_handler (CommandHandler ("mc",add_admin_command ))
    application .add_handler (CommandHandler ("rm",remove_admin_command ))


    logger .info ("Bot started. Press Ctrl+C to stop.")
    application .run_polling (poll_interval =1.0 )

    logger .info ("Bot stopped.")



if __name__ =="__main__":
    try :

        import asyncio 
        import nest_asyncio 

        nest_asyncio .apply ()


        loop =asyncio .get_event_loop ()
        loop .run_until_complete (main ())

    except KeyboardInterrupt :
        logger .info ("Ctrl+C received. Shutting down.")
    except Exception as e :
        logger .exception ("An error occurred during bot execution:")