import ta_cortex_declare_lib3
from cortex4py.api import Api
import cortex4py.exceptions
import json
import sys
import traceback
import splunklib.client as client

# All available data types
dataTypeList = [
        "domain",
        "file",
        "filename",
        "fqdn",
        "hash",
        "ip",
        "mail",
        "mail_subject",
        "other",
        "regexp",
        "registry",
        "uri_path",
        "url",
        "user-agent"]

# Mapping for TLP/PAP codes
colorCode = {
        "WHITE": 0,
        "GREEN": 1,
        "AMBER": 2,
        "RED": 3}

class Cortex(object):

    """ This class is used to represent a Cortex instance"""

    def __init__(self, url = None, apiKey = None, sid = "", logger = None):
        self.logger = logger
        try :
            self.api = Api(url, apiKey)
            # Try to connect to the API by recovering all enabled analyzers
            self.api.analyzers.find_all({}, range='all')
        except cortex4py.exceptions.NotFoundError as e:
            self.logger.error("[10-RESOURCE NOT FOUND] Cortex service is unavailable, is configuration correct ?")
            sys.exit(10)
        except cortex4py.exceptions.ServiceUnavailableError as e:
            self.logger.error("[11-SERVICE UNAVAILABLE] Cortex service is unavailable, is configuration correct ?")
            sys.exit(11)
        except cortex4py.exceptions.AuthenticationError as e:
            self.logger.error("[12-AUTHENTICATION ERROR] Credentials are invalid")
            sys.exit(12)

        self.__sid = sid
        self.__jobs = []

    def getJobs(self):
        """ This function returns all jobs to perform """
        return self.__jobs
    
    def addJob(self, data, dataType, tlp=2, pap=2, analyzers="all"):
        """ This function add a new job to do """

        job = None
        ## Init and check data information
        if (dataType.lower() in dataTypeList):
            dataType = dataType.lower()
        else:
            self.logger.error("[21-WRONG DATA TYPE] This data type ("+dataType+") is not allowed")
            sys.exit(21)

        analyzersObj = []
        # If all analyzers are chosen, we recover them usin the datatype
        if analyzers == "all":
            analyzersObj = self.api.analyzers.get_by_type(dataType)
        else:
            for analyzer in analyzers.replace(" ","").split(";"):
                a = self.api.analyzers.get_by_name(analyzer)
                if a is not None:
                    analyzersObj.append(a)
                else:
                    self.logger.error("[22-ANALYZER NOT FOUND] This analyzer ("+analyzer+") doesn't exist")
                    sys.exit(22)

        job = CortexJob(data, dataType, tlp, pap, analyzersObj, self.logger)
        self.__jobs.append(job)

    def runJobs(self):
        """ Execute all jobs and return the result """
        results = []
        for job in self.__jobs:
            try:
                job_json = job.jsonify()
                job_json["message"] = "sid:"+self.__sid
                for a in job.analyzers:
                    self.logger.debug("JOB sent: "+str(job_json))
                    results.append(self.api.analyzers.run_by_id(a.id, job_json, force=1))
    
            except Exception as e:
                tb = traceback.format_exc()
                self.logger.error(str(e)+" - "+str(tb))
                sys.exit(127)

        self.__jobs = []
        return results


class Settings(object):

    def __init__(self, client, logger = None):
        self.logger = logger
        # get cortex settings
        query = {"output_mode":"json"}
        self.__cortex_settings = json.loads(client.get("TA_cortex_settings/cortex", owner="nobody", app="TA_cortex",**query).body.read())["entry"][0]["content"]
        self.__logging_settings = json.loads(client.get("TA_cortex_settings/logging", owner="nobody", app="TA_cortex",**query).body.read())["entry"][0]["content"]
        self.__storage_passwords = client.storage_passwords
        for s in self.__storage_passwords:
            # Get the API key
            if "cortex_api_key" in s['clear_password']:
                self.__cortex_settings['cortex_api_key'] = str(json.loads(s["clear_password"])["cortex_api_key"])

        # Checks before configure
        cortex_information_required = ["cortex_protocol","cortex_host","cortex_port","cortex_api_key"]
        for i in cortex_information_required:
            if not i in self.__cortex_settings:
                self.logger.error("[10-FIELD MISSING] No \""+i+"\" setting set in \"Configuration\", please configure your Cortex instance under \"Configuration\"")
                sys.exit(10)
    
        # Initiliaze class variables for Cortex
        self.url = self.__cortex_settings["cortex_protocol"]+"://"+self.__cortex_settings["cortex_host"]+":"+self.__cortex_settings["cortex_port"]
        self.apiKey = self.__cortex_settings["cortex_api_key"]

    def getURL(self):
        """ This function returns the URL of the Cortex instance """
        return self.url

    def getApiKey(self):
        """ This function returns the API key of the Cortex instance """
        return self.apiKey

    def getSetting(self, page, key):
        """ This function returns the settings for the concerned page and key """

        result = None
        settings = None
        if (page == "cortex"):
            settings = self.__cortex_settings
        elif (page == "logging"):
            settings = self.__logging_settings

        try:
            result = settings[key]
        except Exception as e:
            self.logger.error("This settings \""+key+"\" doesn't exist for the page "+page)

        return result


class CortexJob(object):

    def __init__(self, data, dataType, tlp=2, pap=2, analyzers="all", logger = None):
        self.logger = logger
        ## Init and check data information
        self.data = data
        if (dataType.lower() in dataTypeList):
            self.dataType = dataType.lower()
        else:
            self.logger.error("[21-WRONG DATA TYPE] This data type ("+dataType+") is not allowed")
            sys.exit(21)

        self.tlp = tlp
        self.pap = pap

        self.analyzers = analyzers

        self.logger.debug('['+self.data+'] DataType: "'+self.dataType+'"')
        self.logger.debug('['+self.data+'] TLP: "'+str(self.tlp)+'"')
        self.logger.debug('['+self.data+'] PAP: "'+str(self.pap)+'"')
        self.logger.debug("["+self.data+"] Analyzers "+str([a.name for a in self.analyzers]))

    @classmethod
    def convert(cls, value, default):
        """ This function is used to convert any "WHITE/GREEN/AMBER/RED" value in an integer """
    
        if (isinstance(value, int)):
            if value in range(0,4):
                return value
            else:
                self.logger.debug("Integer value "+str(value)+" is out of range (0-3), "+str(default)+" default value will be used")
                return default
        elif (isinstance(value, str)):
            value = value.upper()
            if value in colorCode:
                return colorCode[value]
            else:
                self.logger.debug("String value "+str(value)+" is not in ['WHITE','GREEN','AMBER','RED'], "+str(default)+" default value will be used")
                return default
        else:
                self.logger.debug("Value "+str(value)+" is not an integer or a string, "+str(default)+" default value will be used")
                return default

    # 
    def jsonify(self):
        """ This function returns a JSONified version of the object (used by the Cortex API) """

        json = {}

        json["data"] = self.data
        json["dataType"] = self.dataType
        json["tlp"] = self.tlp
        json["pap"] = self.pap

        return json
