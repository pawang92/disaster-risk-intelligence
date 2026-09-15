                    USER
                      |
              CloudFront + WAF
                      |
             React Web Application
                      |
                 Cognito
                      |
                API Gateway
                      |
                  ALB
                      |
             ECS Fargate / FastAPI
                      |
              LangGraph Supervisor
         _____________|________________
        |             |                |
        v             v                v
  Spatial Agent    RAG Agent       Data Agent
        |             |                |
      PostGIS    Bedrock KB          S3/API
        |             |                |
        |          Bedrock FM          |
        |_____________|________________|
                      |
                 Risk Engine
                      |
          _______________________
         |           |           |
      Flood       Exposure     Routing
      Engine      Engine       Engine
         |           |           |
         +-----------+-----------+
                     |
              GeoJSON / Results
                     |
              Map + AI Report