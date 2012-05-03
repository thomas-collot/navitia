#pragma once
#include <string>
#include "type/type.pb.h"
#include "WS_commons/data_structures.h"

/// Crée une version XML d'un message protocol buffer
std::string pb2xml(const google::protobuf::Message* response);

/// Crée une version JSON d'un message protocol buffer
std::string pb2json(const google::protobuf::Message* response, int depth = 0);

/// Construit le message protocol buffer correspondant à l'api de la requête
std::unique_ptr<google::protobuf::Message> create_pb(const webservice::RequestData& request);

/// Construit le message protocol buffer correspondant au nom de l'api
std::unique_ptr<google::protobuf::Message> create_pb(const std::string & api);
