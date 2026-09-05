
import sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from src.services.commercial_routing_v3.evidence_discovery import bridge_match_details_to_evidence, load_discovery_vocabulary
from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer
from src.services.commercial_routing_v3.learning_observer import LearningObserver
print('S13_IMPORT_ALL_OK')
