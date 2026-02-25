from datetime import datetime
from pydantic import BaseModel, ConfigDict

class OrchestratorWorkerOut(BaseModel):
    worker_id: str
    status: str
    is_leader: bool
    last_heartbeat_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
