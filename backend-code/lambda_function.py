import logging
import json
import os
import boto3
import requests
from random import randint
import datetime as dt
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr

#from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.api_client import DefaultApiClient

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.dispatch_components import AbstractResponseInterceptor
from ask_sdk_core.dispatch_components import AbstractRequestInterceptor
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.response_helper import get_plain_text_content
from ask_sdk_model.ui import SimpleCard
from ask_sdk_model import ui
from ask_sdk_model.interfaces.display import (
    ImageInstance, Image, RenderTemplateDirective,
    BackButtonBehavior, BodyTemplate2)
from ask_sdk_model import Response
from ask_sdk_core.exceptions import AskSdkException
import ask_sdk_core.utils as ask_utils
from ask_sdk_model.interfaces.alexa.presentation.apl import (
    RenderDocumentDirective)
from ask_sdk_core.utils import viewport, is_request_type
from ask_sdk_model.services.monetization import (
    EntitledState, PurchasableState, InSkillProductsResponse, Error,
    InSkillProduct)
from ask_sdk_model.interfaces.monetization.v1 import PurchaseResult
from ask_sdk_model.interfaces.connections import SendRequestDirective

logger = logging.getLogger()
#retrieve logging level from lambda environmet properties
level = os.environ['LOG_LEVEL']
logger.setLevel(int(level))

WELCOME_MESSAGE = "Unleash your inner explorer and get to know the cities of Japan." \
    "On your cultural journey, you start with <break time='0.2s'/>" \
    "<prosody volume='x-loud'> a lot </prosody> of money, <prosody volume='x-loud'> and </prosody> energy. " \
    "<amazon:effect name=\"whispered\"> <prosody rate='x-slow'> But the choices you make </prosody> </amazon:effect> " \
    "<break time='0.3s'/> will either increase or decrease them." \
    "Your journey ends when you either run out of money or energy. " \
    "<say-as interpret-as='interjection'>Stay exploring for as long as you can</say-as> before it ends! " \
    "<break time='1s'/> Start by saying explore <voice name='Takumi'><lang xml:lang=\"ja-JP\">Tokyo</lang></voice> or explore <voice name='Mizuki'><lang xml:lang=\"ja-JP\">Kyoto</lang></voice>"

VISIT_CITY_REPROMPT = "Do you want to explore <voice name=\"Takumi\"><lang xml:lang=\"ja-JP\">Tokyo</lang></voice> or <voice name=\"Mizuki\"><lang xml:lang=\"ja-JP\">Kyoto</lang></voice>?"
YES_OR_N0_REPROMPTS = ['Do not stall explorer! Please answer yes or no. If you need a travel tip, say speak to the guide.','Be careful explorer, is your answer yes or no.','You are running out of time explorer! Please answer yes or no.','Explorer, is your answer yes or no. If you need a travel tip, say speak to the guide.','Yes or No, explorer! If you need a travel tip, say speak to the guide.']
GAME_END = "The next question could not be found for your journey. You have reached the end."

#Handler for skill launch with no intent
class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        logger.info("In LaunchRequestHandler")
        logger.info("The user's timezone is {} ".format(get_user_timezone(handler_input)))
        # logger.info("The user's country is {} ".format(get_user_country(handler_input)))
        # logger.info("The user's name is {} ".format(get_user_name(handler_input)))
        logger.info("The user's location is {} ".format(get_user_location(handler_input)))
        response_builder = handler_input.response_builder
        include_display(handler_input)

        #is returning user
        if is_returning_user(handler_input):
            #if active journey; welcome back to journey
            if has_active_journey(handler_input):
                #retrieve current stats
                speak_output = continue_journey(handler_input) 
                reprompt_output = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)]  
            else:
                speak_output = "Welcome back, explorer! You don't have an active journey. " + VISIT_CITY_REPROMPT
                reprompt_output = VISIT_CITY_REPROMPT
        else:
            add_new_user(handler_input.request_envelope.context.system)
            speak_output = WELCOME_MESSAGE
            reprompt_output = VISIT_CITY_REPROMPT

        return response_builder.speak(speak_output).ask(reprompt_output).response

####### Custom Intent Handlers########
class StartJapanExplorerIntentHandler(AbstractRequestHandler):
    """Handler for Start Japan Explorer intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("StartJapanExplorerIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        response_builder = handler_input.response_builder

        try:
            #if user is already on the session, find current journey stats and ask the next Yes/No question
            if is_user_on_session(handler_input):
                logger.info("User is on session, continuing journey") 
                speak_output = continue_journey(handler_input)  
                reprompt_output = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)] 
            else: #if user is not on session are they a new user or do they have an active journey
                #is new user
                if is_returning_user(handler_input):
                    logger.info("Returning user, checking if there's an active journey") 
                    #find current journey stats and ask the next Yes/No question
                    #if active journey; welcome back to journey
                    if has_active_journey(handler_input):
                        logger.info("User has an active journey, continouing journey") 
                        speak_output = continue_journey(handler_input)
                        reprompt_output = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)] 
                    else:
                        logger.info("User on session doesn't have an active journey. Prompting for city") 
                        start_new_journey(handler_input) 
                        speak_output = get_next_question(handler_input.attributes_manager.session_attributes["city"],handler_input.attributes_manager.session_attributes["stats_record"],handler_input)  

                        #Determine city and play correct audio via SSML
                        logger.info("Trying to figure out city. Getting city attribute to speak out in correct voice") 
                        if handler_input.attributes_manager.session_attributes["city"] == 'Tokyo':
                            speak_output = "<audio src=\"https://d28n9h2es30znd.cloudfront.net/rail_starting.mp3\" /> <voice name=\"Takumi\">Welcome to your new <lang xml:lang=\"ja-JP\">Tokyo</lang> journey!</voice> " + speak_output 
                        elif handler_input.attributes_manager.session_attributes["city"] == 'Kyoto':
                            speak_output = "<audio src=\"https://d28n9h2es30znd.cloudfront.net/town_morning.mp3\" /><voice name=\"Mizuki\"> Welcome to your new <lang xml:lang=\"ja-JP\">Kyoto</lang> journey!</voice> " + speak_output 
                        reprompt_output = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)]  
                else:
                    add_new_user(handler_input.request_envelope.context.system)
                    #ask if they want 
                    speak_output = WELCOME_MESSAGE
                    reprompt_output = VISIT_CITY_REPROMPT
        except:
            logger.error("An error in StartJapanExplorerIntentHandler for text type {} ".format(handler_input)) 
            speak_output = "Sorry, explorer! I don't understand what you want to do. That city is probably not supported yet. {}".format(VISIT_CITY_REPROMPT)
            reprompt_output = VISIT_CITY_REPROMPT

        return (
            response_builder
                .speak(speak_output)
                .ask(reprompt_output) #add a reprompt if you want to keep the session open for the user to respond
                .response
        )

####### Built-in Intent Handlers With Custom Code########
class YesIntentHandler(AbstractRequestHandler):
    """Handler for Yes Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("AMAZON.YesIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        # retrieve response to user from database 
        speak_output = getYesorNoResponse(handler_input, 'YesResponseText') 
        
        try:
            if is_game_over(handler_input.attributes_manager.session_attributes["stats_record"]) == False:
                reprompt_output = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)]
                handler_input.response_builder.ask(reprompt_output)
        except:
            logger.error("An error in YesIntentHandler {}".format(handler_input)) 
            speak_output = "Sorry, explorer! I don't understand what you want to do. {} If so, say visit <lang xml:lang=\"ja-JP\">Tokyo</lang> or <lang xml:lang=\"ja-JP\">Kyoto</lang>.".format(VISIT_CITY_REPROMPT)

        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

class NoIntentHandler(AbstractRequestHandler):
    """Handler for No Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("AMAZON.NoIntent")(handler_input)
        
    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = getYesorNoResponse(handler_input, 'NoResponseText')

        try:
            if is_game_over(handler_input.attributes_manager.session_attributes["stats_record"]) == False:
                reprompt_output = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)]
                handler_input.response_builder.ask(reprompt_output)
        except:
            logger.error("An error in NoIntentHandler {}".format(handler_input)) 
            speak_output = "Sorry, explorer! I don't understand what you want to do. {} If so, say visit <lang xml:lang=\"ja-JP\">Tokyo</lang> or <lang xml:lang=\"ja-JP\">Kyoto</lang>.".format(VISIT_CITY_REPROMPT)

        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

class SpeakToGuideIntentHandler(AbstractRequestHandler):
    """Handler for Speak to Guide Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("SpeakToGuideIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        #retrieve ISP products on session
        try:
            #list of products associated to the skill
            isp_response = get_isp_products(handler_input)
            response_builder = handler_input.response_builder

            #check to see if user has a previously purchased a travel tip
            if is_user_entitled(isp_response):
                #if yes, let them use it
                tip_for_question = get_tip_for_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"], handler_input)
                next_question = get_next_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"],handler_input)
                speak_output = "<voice name=\""+ get_polly_voice(handler_input.attributes_manager.session_attributes["city"]) + "\">Hello explorer! " + tip_for_question + "</voice> " + next_question  
                reprompt_output = "<voice name=\""+ get_polly_voice(handler_input.attributes_manager.session_attributes["city"]) + "\"> Explorer, don't hesistate! " + tip_for_question + "</voice> " + next_question 
                include_display(handler_input)
                
                return (
                    response_builder
                        .speak(speak_output)
                        .ask(reprompt_output )
                        .response
                )
            else:
                #if not, upsell (sell) it to them
                upsell_msg = ("You don't currently own {}. Want to learn more?").format(isp_response.in_skill_products[0].summary)
                include_display(handler_input)
                            
                return response_builder.add_directive(
                        SendRequestDirective(name="Upsell",
                                    payload={
                                        "InSkillProduct": {
                                            "productId": isp_response.in_skill_products[0].product_id,
                                        },
                                        "upsellMessage": upsell_msg,
                                    },
                                    token="correlationToken")
                            ).response
        except:
            logger.error("An error in SpeakToGuideIntentHandler for text type {} ".format(handler_input)) 
            speak_output = "A tip is not available at this time. Make sure that you are in active game play. Say visit Tokyo or visit Kyoto"
            reprompt_output = "Would you like to visit Tokyo or Kyoto?"
            return (
                response_builder
                    .speak(speak_output)
                    .ask(reprompt_output) 
                    .response
            ) 

class UpsellResponseHandler(AbstractRequestHandler):
    """This handles the Connections.Response event after an upsell occurs."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_request_type("Connections.Response")(handler_input) and
                handler_input.request_envelope.request.name == "Upsell")

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        response_builder = handler_input.response_builder
        include_display(handler_input)

        if handler_input.request_envelope.request.status.code == "200":
            if is_returning_user(handler_input) and has_active_journey(handler_input):
                if handler_input.request_envelope.request.payload.get("purchaseResult") == PurchaseResult.DECLINED.value:
                    speech = ("Let me repeat the question: {}".format(
                    get_next_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"],handler_input)))
                    reprompt = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)]  
                    return response_builder.speak(speech).ask(reprompt).response          
                elif handler_input.request_envelope.request.payload.get("purchaseResult") == PurchaseResult.ACCEPTED.value or handler_input.request_envelope.request.payload.get("purchaseResult") == PurchaseResult.ALREADY_PURCHASED.value:
                    speech = ("Your exploring tip is: {}. {}".format(get_tip_for_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"], handler_input),
                            get_next_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"],handler_input)))
                    reprompt = YES_OR_N0_REPROMPTS[randint(0, len(YES_OR_N0_REPROMPTS)-1)]  
                    return response_builder.speak(speech).ask(reprompt).response
        else:
            logger.log("Connections.Response indicated failure. "
                       "Error: {}".format(
                handler_input.request_envelope.request.status.message))
            return response_builder.speak(
                "There was an error handling your Upsell request. "
                "Please try again or contact us for help.").response
       
class RefundResponseHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("RefundProductIntent")(handler_input)

    def handle(self, handler_input):
        response_builder = handler_input.response_builder
        isp_response = get_isp_products(handler_input)
        include_display(handler_input)
                        
        return response_builder.add_directive(
                SendRequestDirective(
                    name="Cancel",
                    payload={
                        "InSkillProduct": {
                            "productId": isp_response.in_skill_products[0].product_id
                        }
                    },
                            token="correlationToken")
                    ).response
       
class RefundCancelResponseHandler(AbstractRequestHandler):
    """This handles the Connections.Response event after a refund/cancel occurs."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (is_request_type("Connections.Response")(handler_input) and
                handler_input.request_envelope.request.name == "Cancel")

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech = None
        include_display(handler_input)
        return handler_input.response_builder.speak(speech).response

class HelpIntentHandler(AbstractRequestHandler):
    """Handler for Help Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "Hello, explorer! It's good to see you! To play this game, start by saying, visit <lang xml:lang=\"ja-JP\">Tokyo</lang> or visit <lang xml:lang=\"ja-JP\">Kyoto</lang>. If you're stuck on a hard level, say speak to the guide. Don't forget that your wealth or energy either increase or decrease based on the choices you make while on your journey. When you run out of either, the game ends. " 

        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class CancelOrStopIntentHandler(AbstractRequestHandler):
    """Single handler for Cancel and Stop Intent."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speak_output = "Goodbye!" + getRandomFact() + ". New journeys to Sapporo, Nagasaki, and Okinawa coming soon!"

        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

class FallbackIntentHandler(AbstractRequestHandler):
    
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response
        speech = (
                "Sorry. I cannot help with that. I can help you "
                "continue on your journey by saying explore <lang xml:lang=\"ja-JP\">Tokyo</lang> or vist <lang xml:lang=\"ja-JP\">Kyoto</lang>. "
            )
        reprompt = "I didn't catch that. What can I help you with?"

        return handler_input.response_builder.speak(speech).ask(
            reprompt).response

class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handler for Session End."""
    def can_handle(self, handler_input):
        # type: (HandlerInput) -> bool
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # type: (HandlerInput) -> Response

        updateStats(handler_input)
        speak_output = "Goodbye!" + getRandomFact() + ". New journeys to Sapporo, Nagasaki, and Okinawa coming soon!"

        return (
            handler_input.response_builder
                .speak(speak_output)
                .response
        )

class CatchAllExceptionHandler(AbstractExceptionHandler):
    """Generic error handling to capture any syntax or routing errors."""
    def can_handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> bool
        return True

    def handle(self, handler_input, exception):
        # type: (HandlerInput, Exception) -> Response
        logger.error(exception, exc_info=True)
        logger(handler_input)

        speak_output = "Sorry, I had trouble doing what you asked. Please try again."

        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(speak_output)
                .response
        )

class LoggingResponseInterceptor(AbstractResponseInterceptor):
    """Invoked immediately after execution of the request handler for an incoming request. 
    Used to print response for logging purposes
    """
    def process(self, handler_input, response):
         # type: (HandlerInput, Response) -> None
        logger.debug("Response logged by LoggingResponseInterceptor: {}".format(response))

class LoggingRequestInterceptor(AbstractRequestInterceptor):
    """Invoked immediately before execution of the request handler for an incoming request. 
    Used to print request for logging purposes
    """
    def process(self, handler_input):
        logger.debug("Request received by LoggingRequestInterceptor: {}".format(handler_input.request_envelope))

#---------------general utility functions---------------------
#get random fact on SessionEnd, Cancel, or Stop
def getRandomFact():
    record_number = randint(1,5)
    table = boto3.resource('dynamodb').Table('JPExpFunFacts')
    fact_record = table.query(KeyConditionExpression=Key('RecordNumber').eq(str(record_number))) # dynamo is case-sensitive

    if fact_record['Count'] == 1:
        return fact_record['Items'][0]['Text']
    else:
        logger.error("Cannot find fun fact record") 
        return "Nagasaki is known for its delicious Japanese sake."

def getYesorNoResponse(handler_input, textType):
    logger.info("in getYesorNotResponse") 
    #retrieve the questions details
    table = boto3.resource('dynamodb').Table('JPExpStoryDetails')
    speak_output = GAME_END

    try: 
        #retrieve the Yes or No response for the question
        question_record = table.query(KeyConditionExpression=Key('CityId').eq(get_city_id(handler_input.attributes_manager.session_attributes["city"])) &
        Key('QuestionNumber').eq(handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['QuestionNumber']+1)) 

        #record found
        if question_record['Count'] == 1: 
            #speak the Yes or No details
            speak_output = question_record['Items'][0][textType]
            speak_output = "<voice name=\""+ get_polly_voice(handler_input.attributes_manager.session_attributes["city"]) + "\">" + speak_output + " </voice>"

            #increase current turns by 1 in session
            handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['CurrentTurns'] += 1 
            
            #increase completed question number in session
            handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['QuestionNumber'] += 1

            #actually add to or delete from energy/wealth levels in session
            if textType == 'YesResponseText':
                handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['MoneyLevel'] += question_record['Items'][0]['YesWealthImpact']
                handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['EnergyLevel'] += question_record['Items'][0]['YesEnergyImpact']
            elif textType == 'NoResponseText':
                handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['MoneyLevel'] += question_record['Items'][0]['NoWealthImpact']
                handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['EnergyLevel'] += question_record['Items'][0]['NoEnergyImpact']   

            #determine if the game needs to end; ends if player runs out of health or wealth
            current_wealth = handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['MoneyLevel']
            current_energy = handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['EnergyLevel']

            #you are out of wealth or health -- the game is over
            if is_game_over(handler_input.attributes_manager.session_attributes["stats_record"]):
                speak_output = "<voice name=\""+ get_polly_voice(handler_input.attributes_manager.session_attributes["city"]) + "\">Oh no explorer, you don't have enough wealth or energy to continue on your journey! This means your journey is over. </voice> " 
                #update Game Stats to end the game by setting flag to N
                set_game_flag('N', handler_input)
            #if they are low on wealth/health -- they need a warning
            elif is_warning_needed(current_wealth,current_energy):
                speak_output = "<voice name=\""+ get_polly_voice(handler_input.attributes_manager.session_attributes["city"]) + "\">Be careful explorer, you are running low on wealth or energy. If you need a travel tip, say speak to the guide.</voice> " 
                speak_output = speak_output + " " + get_next_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"],handler_input)
            else: 
                speak_output = speak_output + " " + get_next_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"],handler_input)   
        else: #record not found
            logger.error("That question number doesn't exist: {}".format(handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['QuestionNumber'])) 
            # raise AskSdkException("That question number doesn't exist: {}".format(handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['QuestionNumber'])) 
    except:
        logger.error("An error in getYesorNoResponse for text type {} -- {}".format(textType,handler_input)) 
        speak_output = "Sorry, explorer! I don't understand what you want to do. {}".format(VISIT_CITY_REPROMPT)

    return speak_output 

def updateStats(handler_input):
    logger.info("in update_stats") 
    if is_user_on_session(handler_input) and has_active_journey(handler_input):
        table = boto3.resource('dynamodb').Table('JPExpGameStats')
        table.update_item(
            Key={
                'PlayerNumber': handler_input.attributes_manager.session_attributes["user"]['Items'][0]['PlayerNumber'],
                'CityId' : get_city_id(handler_input.attributes_manager.session_attributes["city"])
            },
            UpdateExpression="set EnergyLevel = :e, MoneyLevel=:m, QuestionNumber=:q, CurrentTurns=:c",
            ConditionExpression="ActiveFlag=:a",
            ExpressionAttributeValues={
                ':e': handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['EnergyLevel'],
                ':m': handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['MoneyLevel'],
                ':q': handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['QuestionNumber'],
                ':c': handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['CurrentTurns'],
                ':a': 'Y'
            },
            ReturnValues="UPDATED_NEW"
        )

        #update max turns 
        maxTurns = handler_input.attributes_manager.session_attributes["user"]['Items'][0]['MaxTurns']
        currentTurns = handler_input.attributes_manager.session_attributes["stats_record"]['Items'][0]['CurrentTurns']

        if currentTurns > maxTurns:
            table = boto3.resource('dynamodb').Table('JPExpUsers')
            table.update_item(
                Key = {
                    'UserId': handler_input.attributes_manager.session_attributes["user"]['Items'][0]['UserId'],
                    'PlayerNumber': handler_input.attributes_manager.session_attributes["user"]['Items'][0]['PlayerNumber'],
                },
                UpdateExpression="set MaxTurns = :m",
                ExpressionAttributeValues={
                    ':m': currentTurns
                }
            )

def get_user(user_id):
    logger.info("in get_user") 

    table = boto3.resource('dynamodb').Table('JPExpUsers')
    user = table.query(KeyConditionExpression=Key('UserId').eq(user_id)) # dynamo is case-sensitive
    return user  

def is_returning_user(handler_input):
    logger.info("in is_returning_user") 
    user_record = get_user(handler_input.request_envelope.context.system.user.user_id)
    if user_record['Count'] == 1:
        #add user to session
        handler_input.attributes_manager.session_attributes["user"] = user_record
        return True
    else:
        return False
  
def add_new_user(system):
    logger.info("in add_new_user") 
    table = boto3.resource('dynamodb').Table('JPExpUsers')
    date = str(dt.datetime.today().strftime("%Y-%m-%d"))
    
    table.put_item(
        Item={
            "Name": "TBD-USERAPI",
            "PlayerNumber": randint(1, 1000000000),
            "DeviceId": system.device.device_id,
            "Date": date,
            "UserId": system.user.user_id,
            "Country": "TBD-ADDRESSAPI",
            "Email": "TBD-CUSTINFOAPI",
            "MaxTurns": 0
        }
    )  # dynamo is case-sensitive

def is_user_on_session(handler_input):
    if 'city' in handler_input.attributes_manager.session_attributes:
        if 'stats_record' in handler_input.attributes_manager.session_attributes:
            return True
        else:
            return False
    else:
        return False

def has_active_journey(handler_input):
    
    logger.info("in has_active_journey") 

    #get user from session
    user = handler_input.attributes_manager.session_attributes["user"]
    
    #determine if on an active journey
    table = boto3.resource('dynamodb').Table('JPExpGameStats')
    stats_record = table.query(KeyConditionExpression=Key('PlayerNumber').eq(user['Items'][0]['PlayerNumber'])) 

    if stats_record['Count'] == 1:
        if stats_record['Items'][0]['ActiveFlag'] == 'Y':
            if 'city' not in handler_input.attributes_manager.session_attributes:
                handler_input.attributes_manager.session_attributes["city"] = get_city_name(stats_record['Items'][0]['CityId'])
                
            if 'stats_record' not in handler_input.attributes_manager.session_attributes:
                handler_input.attributes_manager.session_attributes["stats_record"] = stats_record
            return True
        else:
            return False
    elif stats_record['Count'] > 1: #user has multiple journeys
        #find the active journey
        for x in range(0,stats_record['Count']):
            item = stats_record['Items'][x]
            if item['ActiveFlag'] == 'Y':
                if 'city' not in handler_input.attributes_manager.session_attributes:
                    handler_input.attributes_manager.session_attributes["city"] =  get_city_name(item['CityId'])
                
                if 'stats_record' not in handler_input.attributes_manager.session_attributes:
                    new_item = {'Items':[item]}
                    handler_input.attributes_manager.session_attributes["stats_record"] = new_item
                return True
        #if no active journey, return false
        return False
    else:
        return False

def get_city_name(CityId):
    logger.info("in get_city_name") 
    table = boto3.resource('dynamodb').Table('JPExpCities')
    city_record = table.query(KeyConditionExpression=Key('CityId').eq(CityId)) # dynamo is case-sensitive

    if city_record['Count'] == 1:
        return city_record['Items'][0]['CityName']
    else:
        logger.error("Cannot find city name for given id {}".format(CityId)) 
        raise AskSdkException("Cannot find city name for given id {}".format(CityId)) 

def get_city_id(CityName):
    logger.info("in get_city_id") 
    table = boto3.resource('dynamodb').Table('JPExpCities')
    city_record = table.query(
        IndexName='CityName-index',
        KeyConditionExpression=Key('CityName').eq(CityName)) # dynamo is case-sensitive
    
    if city_record['Count'] == 1:
        return city_record['Items'][0]['CityId']
    else:
        logger.error("Cannot find city id for given name {}".format(CityName)) 
        raise AskSdkException("Cannot find city id for given name {}".format(CityName)) 

def continue_journey(handler_input):
    logger.info("in continue_journey") 
    speak_output = "<voice name=\""+ get_polly_voice(handler_input.attributes_manager.session_attributes["city"]) + "\">Welcome back explorer! It's good to see you!</voice> " 

    speak_output = speak_output + get_next_question(handler_input.attributes_manager.session_attributes["city"], handler_input.attributes_manager.session_attributes["stats_record"],handler_input)  

    return speak_output
    
def get_next_question(cityname, stats, handler_input):
    logger.info(" in get_next_question City Name: {}".format(cityname))
    logger.info(" in get_next_question Stats Completed Question Number: {}".format(stats['Items'][0]['QuestionNumber']+1))
    #return next question
    table = boto3.resource('dynamodb').Table('JPExpStories')
    speak_output = GAME_END
    
    #retrieve the next question for the particular city
    question_record = table.query(KeyConditionExpression=Key('CityId').eq(get_city_id(cityname)) &
    Key('QuestionNumber').eq(stats['Items'][0]['QuestionNumber']+1)) #current completed question + 1

    #record found
    if question_record['Count'] == 1: 
        speak_output = question_record['Items'][0]['QuestionText']    
    else: #record not found
        logger.error("That question number doesn't exist: {}".format(stats['Items'][0]['QuestionNumber']+1)) 
        updateStats(handler_input) #current values
        set_game_flag('N', handler_input) #flag game as over
        stats['Items'][0]['ActiveFlag'] = 'N' #update value on session
        #raise AskSdkException("That question number doesn't exist: {}".format(stats['Items'][0]['QuestionNumber']+1)) 

    return speak_output

#get correct Polly voice based on selected city
def get_polly_voice(city):
    logger.info("in get_polly_voice") 
    if city == 'Tokyo':
       return "Takumi"
    elif city == 'Kyoto':
       return "Mizuki"

def set_game_flag(value, handler_input):
    logger.info("in set_game_flag") 
    if is_user_on_session(handler_input) and has_active_journey(handler_input):
        table = boto3.resource('dynamodb').Table('JPExpGameStats')
        table.update_item(
            Key={
                'PlayerNumber': handler_input.attributes_manager.session_attributes["user"]['Items'][0]['PlayerNumber'],
                'CityId' : get_city_id(handler_input.attributes_manager.session_attributes["city"])
            },
            UpdateExpression="set ActiveFlag=:n",
            ConditionExpression="ActiveFlag=:a",
            ExpressionAttributeValues={
                ':n': 'N',
                ':a': 'Y'
            }
        )

def start_new_journey(handler_input):
    #create initial game stat record
    logger.info("in start_new_journey") 
    table = boto3.resource('dynamodb').Table('JPExpGameStats')
    date = str(dt.datetime.today().strftime("%Y-%m-%d"))

    #add selected city to session
    handler_input.attributes_manager.session_attributes["city"] = handler_input.request_envelope.request.intent.slots['city'].value

    new_journey = {
        "PlayerNumber": handler_input.attributes_manager.session_attributes["user"]['Items'][0]['PlayerNumber'],
        "QuestionNumber": 0,
        "CityId": get_city_id(handler_input.request_envelope.request.intent.slots['city'].value),
        "CurrentTurns": 0,
        "MoneyLevel": 50,
        "EnergyLevel": 50,
        "ActiveFlag" : 'Y',
        "Date": date
    }

    table.put_item(
            Item=new_journey
        )  # dynamo is case-sensitive

    #put the stats on the session
    handler_input.attributes_manager.session_attributes["stats_record"] = {'Items':[new_journey]}

def is_game_over(stats):
    #game is over if they run out of wealth or energy or there are no questions left
    if stats['Items'][0]['MoneyLevel'] <= 0 or stats['Items'][0]['EnergyLevel'] <=0 or stats['Items'][0]['ActiveFlag'] == 'N':
        return True
    else:
        return False

def is_warning_needed(current_wealth,current_energy):
    if current_wealth <= 10 or current_energy <= 10:
        return True
    else:
        return False

#add graphical component to the skill
def supports_display(handler_input):
    # type: (HandlerInput) -> bool
    """Check if display is supported by the skill."""
    #check the incoming request to the skill from the AVS to determine if the device the user invoked the skill on has a screen
    try:
        if hasattr(handler_input.request_envelope.context.system.device.supported_interfaces, 'display'):
            if(handler_input.request_envelope.context.system.device.supported_interfaces.display is not None):
                return True
            else:
                return False
        else:
            return False
    except:
        return False


#add graphical component to the skill
def include_display(handler_input):
    logger.info("in include_display") 
    #APL Directive Code
    if supports_apl(handler_input):
        handler_input.response_builder.add_directive(
            RenderDocumentDirective(
                document=load_apl_document("main.json"),
                datasources=load_apl_document("datasources.json")
            )
        )

def supports_apl(handler_input):
    logger.info("in support_apl") 
    # type: (HandlerInput) -> bool
    """Check if display is supported by the skill."""
    try:
        if hasattr(handler_input.request_envelope.context.system.device.supported_interfaces, 'alexa_presentation_apl'):
            if(handler_input.request_envelope.context.system.device.supported_interfaces.alexa_presentation_apl is not None):
                return True
            else:
                return False
        else:
            return False
    except:
        return False

#APL helper functions
def load_apl_document(file_path):
    logger.info("in load_apl_document") 
    # type: (str) -> Dict[str, Any]
    """Load the apl json document at the path into a dict object."""
    with open(file_path) as f:
        return json.load(f)


#Alexa Settings API
def get_user_timezone(handler_input):
    base_uri = handler_input.request_envelope.context.system.api_endpoint
    device_id = handler_input.request_envelope.context.system.device.device_id
    api_access_token = handler_input.request_envelope.context.system.api_access_token
    response = requests.get(base_uri + "/v2/devices/" + device_id + "/settings/System.timeZone", 
                    headers = {
                        'Accept': 'application/json',
                        'Authorization': 'Bearer {}'.format(api_access_token)
                    }
                )
    data = json.loads(response.text)
    return data

#Device Address API
def get_user_country(handler_input):
    base_uri = handler_input.request_envelope.context.system.api_endpoint
    device_id = handler_input.request_envelope.context.system.device.device_id
    api_access_token = handler_input.request_envelope.context.system.api_access_token
    response = requests.get(base_uri + "/v1/devices/" + device_id + "/settings/address/countryAndPostalCode", 
                    headers = {
                        'Accept': 'application/json',
                        'Authorization': 'Bearer {}'.format(api_access_token)
                    }
                )
    data = json.loads(response.text)

    logger.info("in get_user_country - device address API response: {}".format(data)) 
    
    return data["countryCode"]

#Customer Profile API
#/v2/accounts/~current/settings/Profile.givenName
#/v2/accounts/~current/settings/Profile.email
#/v2/accounts/~current/settings/Profile.mobileNumber
def get_user_name(handler_input):
    base_uri = handler_input.request_envelope.context.system.api_endpoint
    api_access_token = handler_input.request_envelope.context.system.api_access_token
    response = requests.get(base_uri + "/v2/accounts/~current/settings/Profile.name", 
                    headers = {
                        'Accept': 'application/json',
                        'Authorization': 'Bearer {}'.format(api_access_token)
                    }
                )
    data = json.loads(response.text)

    logger.info("in get_user_name - customer profile API response: {}".format(data)) 

    return data

#Location Services
#If the device doesn't support location services, nothing is returned
#Test this from Alexa app on mobile phone instead of stationary Echo device
def get_user_location(handler_input):
    if hasattr(handler_input.request_envelope.context.system.device.supported_interfaces, 'geolocation'):
        if hasattr(handler_input.request_envelope.context.geolocation, 'coordinate'):
            return handler_input.request_envelope.context.geolocation.coordinate
        else:
            return "unsupported on this device"
    else:
        return "unsupported on this device"

def include_display_template(handler_input):
    logger.info("in include_display_template") 
    
    #Display Template Code
    if supports_display(handler_input):
        img = Image(
            sources=[ImageInstance(url="https://d28n9h2es30znd.cloudfront.net/japan_travel_large.jpeg")])
        title = "Japan Explorer"
        primary_text = get_plain_text_content(
            primary_text="Echo Display Screen: RenderTemplateDirective with BodyTemplate2")

        handler_input.response_builder.add_directive(
            RenderTemplateDirective(
                BodyTemplate2(
                    back_button=BackButtonBehavior.VISIBLE,
                    image=img, 
                    title=title,
                    text_content=primary_text)))


#add graphical card to the skill
def include_card(response_builder):
    logger.info("in include_card") 

    #Card Code
    response_builder.set_card(
        ui.StandardCard(
            title="Japan Explorer",
            text="Travelling is breathing",
            image=ui.Image(
                small_image_url="https://d28n9h2es30znd.cloudfront.net/japan_travel_small.jpeg",
                large_image_url="https://d28n9h2es30znd.cloudfront.net/japan_travel_large.jpeg"
            )
        )
    )

#ISP helper functions
def get_isp_products(handler_input):
    locale = handler_input.request_envelope.request.locale
    mservice = handler_input.service_client_factory.get_monetization_service()
    response = mservice.get_in_skill_products(locale)
    
    #add products to session
    handler_input.attributes_manager.session_attributes["products"] = response
    return response

def is_user_entitled(response):
    entitled_product_list = [
        l for l in response.in_skill_products if (
                l.entitled == EntitledState.ENTITLED)]
    
    if entitled_product_list:
        return True
    else:
        return False

def get_tip_for_question(cityname, stats, handler_input):
    table = boto3.resource('dynamodb').Table('JPExpStoryDetails')
    speak_output = GAME_END

    #retrieve hint/tip for ISP and store on session
    question_record = table.query(KeyConditionExpression=Key('CityId').eq(get_city_id(cityname)) &
    Key('QuestionNumber').eq(stats['Items'][0]['QuestionNumber']+1)) #current completed question + 1

    #record found
    if question_record['Count'] == 1: 
        speak_output = question_record['Items'][0]['Tip']
        handler_input.attributes_manager.session_attributes['Tip'] = question_record['Items'][0]['Tip']
    else: #record not found
        logger.error("That question number doesn't exist: {}".format(stats['Items'][0]['QuestionNumber']+1)) 
        #raise AskSdkException("That question number doesn't exist: {}".format(stats['Items'][0]['QuestionNumber']+1)) 

    return speak_output

# The SkillBuilder object acts as the entry point for your skill, routing all request and response
# payloads to the handlers above. Make sure any new handlers or interceptors you've
# defined are included below. The order matters - they're processed top to bottom.

# Skill Builder object
sb = CustomSkillBuilder(api_client=DefaultApiClient())

# Add all request handlers to the skill.
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(StartJapanExplorerIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(YesIntentHandler())
sb.add_request_handler(NoIntentHandler())
sb.add_request_handler(SpeakToGuideIntentHandler())
sb.add_request_handler(UpsellResponseHandler())
sb.add_request_handler(RefundResponseHandler())
sb.add_request_handler(RefundCancelResponseHandler())

# Add exception handler to the skill.
sb.add_exception_handler(CatchAllExceptionHandler())

# Add request and response interceptors
sb.add_global_response_interceptor(LoggingResponseInterceptor())
sb.add_global_request_interceptor(LoggingRequestInterceptor())

# Expose the lambda handler function that can be tagged to AWS Lambda handler
handler = sb.lambda_handler()