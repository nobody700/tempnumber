

import os 

BOT_TOKEN =os .environ .get ("BOT_TOKEN","7234996198:AAGp3fLTZzsomsdGCY6EXcTazZtdff2hSIg")
DEFAULT_ADMIN_ID =int (os .environ .get ("DEFAULT_ADMIN_ID","7069274296"))

HEADERS ={
"accept-encoding":"gzip",
"user-agent":"okhttp/4.9.2",
}
API_AUTH_URL ="https://api-1.online/post/"
API_COUNTRIES_URL ="https://api-1.online/get/"
API_NUMBERS_URL ="https://api-1.online/post/"
API_SMS_URL ="https://api-1.online/post/getFreeMessages"

NUMBER_LIMIT_PER_PERIOD =5 
RATE_LIMIT_PERIOD_SECONDS =3 *3600 

COUNTRIES_PER_PAGE =10 
NUMBERS_PER_PAGE =10 

PERSISTENCE_FILE ="persistence.pkl"

REFRESH_WAIT_SECONDS =15 