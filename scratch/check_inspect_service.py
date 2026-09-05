#!/usr/bin/env python3
import sys
import os
import inspect

sys.path.insert(0, ".")

import tender_documents_research.document_processor.context_validator_service as cvs

print("cvs.__file__:", cvs.__file__)
print("rebuild_affected_evidence file:", inspect.getfile(cvs.rebuild_affected_evidence))
