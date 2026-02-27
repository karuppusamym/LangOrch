import logging
import sys
from pythonjsonlogger import jsonlogger
import contextvars

# Context variables for correlation
ctx_run_id = contextvars.ContextVar("run_id", default=None)
ctx_node_id = contextvars.ContextVar("node_id", default=None)
ctx_step_id = contextvars.ContextVar("step_id", default=None)
ctx_tenant_id = contextvars.ContextVar("tenant_id", default=None)

class CorrelationJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Inject context variables if present
        run_id = ctx_run_id.get()
        if run_id:
            log_record["run_id"] = run_id
            
        node_id = ctx_node_id.get()
        if node_id:
            log_record["node_id"] = node_id
            
        step_id = ctx_step_id.get()
        if step_id:
            log_record["step_id"] = step_id
            
        tenant_id = ctx_tenant_id.get()
        if tenant_id:
            log_record["tenant_id"] = tenant_id

def setup_logger(log_format: str = "text", log_level: str = "INFO"):
    """Configure the root logger."""
    root_logger = logging.getLogger()
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    handler = logging.StreamHandler(sys.stdout)
    
    if log_format.lower() == "json":
        formatter = CorrelationJsonFormatter(
            '%(asctime)s %(levelname)s %(name)s %(message)s',
            rename_fields={"levelname": "level", "asctime": "timestamp"}
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)
    
    # Silence third-party noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.WARNING)

    return root_logger
