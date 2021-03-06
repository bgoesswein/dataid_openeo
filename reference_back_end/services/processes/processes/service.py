""" Process Discovery """

from nameko.rpc import rpc, RpcProxy
from nameko_sqlalchemy import DatabaseSession
from sqlalchemy import exc
from uuid import uuid4
from copy import deepcopy

from .models import Base, Process, Parameter, ProcessGraph, ProcessNode
from .schema import ProcessSchema, ProcessNodeSchema, ProcessGraphShortSchema, ProcessGraphFullSchema
from .dependencies import NodeParser, Validator
from jsonschema import ValidationError
import logging

class ServiceException(Exception):
    """ServiceException raises if an exception occured while processing the 
    request. The ServiceException is mapping any exception to a serializable
    format for the API gateway.
    """

    def __init__(self, service:str, code: int, user_id: str, msg: str,
                 internal: bool=True, links: list=[]):
        self._service = service
        self._code = code
        user_id = "openeouser"
        self._user_id = user_id
        self._msg = msg
        self._internal = internal
        self._links = links

    def to_dict(self) -> dict:
        """Serializes the object to a dict.

        Returns:
            dict -- The serialized exception
        """

        return {
            "status": "error",
            "service": self._service,
            "code": self._code,
            "user_id": self._user_id,
            "msg": self._msg,
            "internal": self._internal,
            "links": self._links
        }


class ProcessesService:
    """Discovery of processes that are available at the back-end.
    """

    name = "processes"
    db = DatabaseSession(Base)

    @rpc
    def create(self, user_id: str, **process_args):
        user_id = "openeouser"
        """The request will ask the back-end to create a new process using the description send in the request body.

        Keyword Arguments:
            user_id {str} -- The identifier of the user (default: {None})
        """
        myuser_id = "openeouser"
        message = ""
        try:
            message = message + "1"
            parameters = process_args.pop("parameters", {})
            message = message + "2"
            process = Process(**{"user_id": myuser_id, **process_args})
            message = message + "3"
            for parameter_name, parameter_specs in parameters.items():
                parameter = Parameter(**{"name":parameter_name, "process_id": process.id, **parameter_specs})
                self.db.add(parameter)
            message = message + "4"
            self.db.add(process)
            message = message + "5"
            self.db.commit()
            message = message + "6"

            return {
                "status": "success "+message,
                "code": 201,
                "data": "The process {0} has been successfully created.".format(process_args["name"])
            }
        except exc.IntegrityError as exp:
            msg = str(exp) + message #"Process '{0}' does already exist.".format(
                #process_args["name"])
            return ServiceException(ProcessesService.name, 400, myuser_id, msg, internal=False,
                                    links=["#tag/EO-Data-Discovery/paths/~1processes/post"]).to_dict()
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, myuser_id, str(exp)).to_dict()

    @rpc
    def get_all(self, user_id: str="openeouser"):
        user_id = "openeouser"
        """The request asks the back-end for available processes and returns detailed process descriptions.
        
        Keyword Arguments:
            user_id {str} -- The identifier of the user (default: {None})
        """

        try:
            processes = self.db.query(Process).order_by(Process.name).all()

            return {
                "status": "success",
                "code": 200,
                "data": ProcessSchema(many=True).dump(processes).data
            }
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()

    @rpc
    def resetdb(self):
        user_id = "openeouser"
        message = "; start"
        try:
            self.db.query(ProcessNode).delete(synchronize_session='evaluate')
            message = message + "; deletedPN"
            self.db.commit()
            message = message + "; commit"
            self.db.query(ProcessGraph).delete(synchronize_session='evaluate')
            message = message + "; deletedPG"
            self.db.commit()
            message = message + "; commit"

            return {
                "status": "success",
                "code": 200,
                "data": message
            }
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id+message, str(exp)+message,
                                    links=["#tag/Job-Management/paths/~1process_graphs/get"]).to_dict()

    # @rpc
    # def get_processes(self, user_id):
    #     try:
    #         processes = self.db.query(Process).filter(Process.process_id.like("%{0}%".format(qname))).all() \
    #                     if qname else \
    #                     self.db.query(Process).order_by(Process.process_id).all()

    #         dumped_processes = []
    #         for process in processes:
    #             dumped_processes.append(ProcessSchemaShort().dump(process).data)

    #         return {
    #             "status": "success",
    #             "data": dumped_processes
    #         }
    #     except Exception as exp:
    #         return ServiceException(500, user_id, str(exp)).to_dict()

    # @rpc
    # def get_process(self, user_id, process_id):
    #     try:
    #         process = self.db.query(Process).filter_by(process_id=process_id).first()

    #         if not process:
    #             raise NotFound("Process '{0}' does not exist.".format(process_id))

    #         return {
    #             "status": "success",
    #             "data": ProcessSchema().dump(process)
    #         }
    #     except NotFound as exp:
    #         return ServiceException(400, user_id, str(exp), internal=False,
    #             links=["#tag/EO-Data-Discovery/paths/~1data~1{data_id}/get"]).to_dict() # TODO
    #     except Exception as exp:
    #         return ServiceException(500, user_id, str(exp)).to_dict()

    # @rpc
    # def get_all_processes_full(self, user_id):
    #     try:
    #         processes = self.db.query(Process).order_by(Process.process_id).all()

    #         dumped_processes = []
    #         for process in processes:
    #             dumped_processes.append(ProcessSchemaFull().dump(process).data)

    #         return {
    #             "status": "success",
    #             "data": dumped_processes
    #         }
    #     except Exception as exp:
    #         return ServiceException(500, user_id, str(exp)).to_dict()


class ProcessesGraphService:
    """Management of stored process graphs.
    """

    name = "process_graphs"
    db = DatabaseSession(Base)
    process_service = RpcProxy("processes")
    data_service = RpcProxy("data")
    validator = Validator()
    node_parser = NodeParser()

    @rpc
    def get(self, user_id: str, process_graph_id: str):
        user_id = "openeouser"
        try:
            process_graph = self.db.query(ProcessGraph).filter_by(id=process_graph_id).first()

            if process_graph is None:
                return ServiceException(ProcessesService.name, 400, user_id, 
                    "The process_graph with id '{0}' does not exist.".format(process_graph_id), internal=False, 
                    links=["#tag/Job-Management/paths/~1process_graphs~1{process_graph_id}/get"]).to_dict()

            # TODO: Permission (e.g admin)
            if process_graph.user_id != user_id:
                return ServiceException(ProcessesService.name, 401, user_id,
                    "You are not allowed to access this ressource.", internal=False, 
                    links=["#tag/Job-Management/paths/~1process_graphs~1{process_graph_id}/get"]).to_dict()

            return {
                    "status": "success",
                    "code": 200,
                    "data": ProcessGraphFullSchema().dump(process_graph).data
            }
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()

    @rpc
    def delete(self, user_id: str, process_graph_id: str):
        user_id = "openeouser"
        try:
            raise Exception("Not implemented yet!")
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp),
                    links=["#tag/Job-Management/paths/~1process_graphs~1{process_graph_id}/delete"]).to_dict()
    
    @rpc
    def modify(self, user_id: str, process_graph_id: str, **process_graph_args):
        user_id = "openeouser"
        try:
            raise Exception("Not implemented yet!")
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp), 
                    links=["#tag/Job-Management/paths/~1process_graphs~1{process_graph_id}/patch"]).to_dict()

    @rpc
    def get_all(self, user_id: str):
        user_id = "openeouser"
        try:
            process_graphs = self.db.query(ProcessGraph).order_by(ProcessGraph.created_at).all()

            return {
                "status": "success",
                "code": 200,
                "data": ProcessGraphShortSchema(many=True).dump(process_graphs).data
            }
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp),
                    links=["#tag/Job-Management/paths/~1process_graphs/get"]).to_dict()

    @rpc
    def create(self, user_id: str, **process_graph_args):
        """The request will ask the back-end to create a new process using the description send in the request body.

        Keyword Arguments:
            user_id {str} -- The identifier of the user (default: {None})
        """
        user_id = "openeouser"
        try:
            process_graph_json = deepcopy(process_graph_args.get("process_graph", {}))

            validate = self.validate(user_id, process_graph_json)
            if validate["status"] == "error":
               return validate

            # Get all processes
            process_response = self.process_service.get_all()
            if process_response["status"] == "error":
               return process_response
            processes = process_response["data"]
            
            process_graph = ProcessGraph(**{"user_id": user_id, **process_graph_args})
            message = str(processes)
            nodes = self.node_parser.parse_process_graph(process_graph_json, processes)

            message = message + " ;; " + str(nodes)

            imagery_id = None
            for idx, node in enumerate(nodes):
                process_node = ProcessNode(
                    user_id=user_id,
                    seq_num=len(nodes) - (idx + 1),
                    imagery_id=imagery_id,
                    process_graph_id=process_graph.id,
                    **node)
                self.db.add(process_node)
                imagery_id = process_node.id

            process_graph_id = str(process_graph.id)

            process_graph.description = message

            self.db.add(process_graph)
            self.db.commit()

            return {
                "status": "success",
                "code": 201,
                "headers": {"Location": "https://openeo.eodc.eu/api/v0/TBD"},
                "service_data": process_graph_id
            }
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()
    
    @rpc
    def validate(self, user_id: str, process_graph: dict):
        """The request will ask the back-end to create a new process using the description send in the request body.

        Keyword Arguments:
            user_id {str} -- The identifier of the user (default: {None})
        """
        # TODO: RESPONSE HEADERS -> OpenEO-Costs
        user_id = "openeouser"
        try:
            # Get all processes
            process_response = self.process_service.get_all()
            if process_response["status"] == "error":
               return process_response
            processes = process_response["data"]

            # Get all products
            product_response = self.data_service.get_all_products()
            if product_response["status"] == "error":
               return product_response
            products = product_response["data"]

            self.validator.update_datasets(processes, products)
            self.validator.validate_node(process_graph)

            return {
                "status": "success",
                "code": 204
            }
        except ValidationError as exp:
            return ServiceException(ProcessesService.name, 400, user_id, exp.message, internal=False,
                                    links=["#tag/EO-Data-Discovery/paths/~1process_graph/post"]).to_dict()
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()

    @rpc
    def get_nodes(self, user_id: str, process_graph_id: str):
        user_id = "openeouser"

        try:
            process_graph = self.db.query(ProcessGraph).filter_by(id=process_graph_id).first()
            nodes = sorted(process_graph.nodes, key=lambda n: n.seq_num) 

            return {
                    "status": "success",
                    "data": ProcessNodeSchema(many=True).dump(nodes).data
            }
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()

    @rpc
    def get_process_graph(self, user_id: str, process_graph_id: str):
        user_id = "openeouser"

        try:
            process_graph = self.db.query(ProcessGraph).filter_by(id=process_graph_id).first()

            return str(process_graph.process_graph)

        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()

    @rpc
    def get_updated(self, user_id: str, process_graph_id: str):
        user_id = "openeouser"

        try:
            process_graph = self.db.query(ProcessGraph).filter_by(id=process_graph_id).first()

            if "updated" in process_graph.process_graph:
                return str(process_graph.process_graph["updated"])
            else:
                return None
        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()

    @rpc
    def get_deleted(self, user_id: str, process_graph_id: str):
        user_id = "openeouser"

        try:
            process_graph = self.db.query(ProcessGraph).filter_by(id=process_graph_id).first()

            if "deleted" in process_graph.process_graph:
                return process_graph.process_graph["deleted"]
            else:
                return False

        except Exception as exp:
            return ServiceException(ProcessesService.name, 500, user_id, str(exp)).to_dict()

    @rpc
    def updaterecord(self, user_id: str, process_graph: dict):
        user_id = "openeouser"
     #   try:

        logging.basicConfig(level=logging.DEBUG)

        logging.info(str(process_graph))
        if "updatetime" in process_graph:
            self.data_service.set_updated(process_graph["updatetime"])
            logging.info("updatetime")
        if "deleted" in process_graph:
            self.data_service.set_deleted(process_graph["deleted"])
            logging.info("deleted")
        return {
            "status": "success",
            "code": 201,
            "headers": {"Location": ""}
        }
      #  except Exception as exp:
       #     return ServiceException(500, user_id, str(exp),
        #                                links=["#tag/Job-Management/paths/~1jobs/post"]).to_dict()

