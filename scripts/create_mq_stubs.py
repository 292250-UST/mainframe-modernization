import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import COPYBOOK_DIR

# IBM MQ system copybook stubs
# These define MQ API structures (MQMD, MQOD, MQPMO, MQGMO etc.)
stubs = {
    "CMQV": """
      * IBM MQ Constants (CMQV)
       01 MQCC-OK             PIC S9(9) COMP VALUE 0.
       01 MQCC-WARNING        PIC S9(9) COMP VALUE 1.
       01 MQCC-FAILED         PIC S9(9) COMP VALUE 2.
       01 MQRC-NONE           PIC S9(9) COMP VALUE 0.
       01 MQRC-NOT-CONNECTED  PIC S9(9) COMP VALUE 2009.
       01 MQRC-Q-FULL         PIC S9(9) COMP VALUE 2053.
       01 MQOO-INPUT-AS-Q-DEF PIC S9(9) COMP VALUE 1.
       01 MQOO-OUTPUT         PIC S9(9) COMP VALUE 16.
       01 MQGMO-NO-WAIT       PIC S9(9) COMP VALUE 0.
       01 MQGMO-WAIT          PIC S9(9) COMP VALUE 1.
       01 MQPMO-NO-SYNCPOINT  PIC S9(9) COMP VALUE 4.
    """,
    "CMQMDV": """
      * IBM MQ Message Descriptor (MQMD)
       01 MQM-MD.
          05 MQM-MD-STRUCID    PIC X(4)  VALUE 'MD  '.
          05 MQM-MD-VERSION    PIC S9(9) COMP VALUE 1.
          05 MQM-MD-REPORT     PIC S9(9) COMP VALUE 0.
          05 MQM-MD-MSGTYPE    PIC S9(9) COMP VALUE 8.
          05 MQM-MD-EXPIRY     PIC S9(9) COMP VALUE -1.
          05 MQM-MD-FEEDBACK   PIC S9(9) COMP VALUE 0.
          05 MQM-MD-ENCODING   PIC S9(9) COMP VALUE 0.
          05 MQM-MD-CODEDCHARSETID PIC S9(9) COMP VALUE -2.
          05 MQM-MD-FORMAT     PIC X(8)  VALUE SPACES.
          05 MQM-MD-PRIORITY   PIC S9(9) COMP VALUE -1.
          05 MQM-MD-PERSISTENCE PIC S9(9) COMP VALUE -1.
          05 MQM-MD-MSGID      PIC X(24) VALUE SPACES.
          05 MQM-MD-CORRELID   PIC X(24) VALUE SPACES.
          05 MQM-MD-REPLYTOQ   PIC X(48) VALUE SPACES.
          05 MQM-MD-REPLYTOQMGR PIC X(48) VALUE SPACES.
    """,
    "CMQODV": """
      * IBM MQ Object Descriptor (MQOD)
       01 MQM-OD.
          05 MQM-OD-STRUCID    PIC X(4)  VALUE 'OD  '.
          05 MQM-OD-VERSION    PIC S9(9) COMP VALUE 1.
          05 MQM-OD-OBJECTTYPE PIC S9(9) COMP VALUE 1.
          05 MQM-OD-OBJECTNAME PIC X(48) VALUE SPACES.
          05 MQM-OD-OBJECTQMGRNAME PIC X(48) VALUE SPACES.
          05 MQM-OD-DYNAMICQNAME PIC X(48) VALUE SPACES.
          05 MQM-OD-ALTERNATEUSERID PIC X(12) VALUE SPACES.
    """,
    "CMQGMOV": """
      * IBM MQ Get Message Options (MQGMO)
       01 MQM-GMO.
          05 MQM-GMO-STRUCID   PIC X(4)  VALUE 'GMO '.
          05 MQM-GMO-VERSION   PIC S9(9) COMP VALUE 1.
          05 MQM-GMO-OPTIONS   PIC S9(9) COMP VALUE 0.
          05 MQM-GMO-WAITINTERVAL PIC S9(9) COMP VALUE 0.
          05 MQM-GMO-SIGNAL1   PIC S9(9) COMP VALUE 0.
          05 MQM-GMO-SIGNAL2   PIC S9(9) COMP VALUE 0.
          05 MQM-GMO-RESOLVEDQNAME PIC X(48) VALUE SPACES.
    """,
    "CMQPMOV": """
      * IBM MQ Put Message Options (MQPMO)
       01 MQM-PMO.
          05 MQM-PMO-STRUCID   PIC X(4)  VALUE 'PMO '.
          05 MQM-PMO-VERSION   PIC S9(9) COMP VALUE 1.
          05 MQM-PMO-OPTIONS   PIC S9(9) COMP VALUE 0.
          05 MQM-PMO-TIMEOUT   PIC S9(9) COMP VALUE -1.
          05 MQM-PMO-CONTEXT   PIC S9(9) COMP VALUE 0.
          05 MQM-PMO-RESOLVEDQNAME PIC X(48) VALUE SPACES.
          05 MQM-PMO-RESOLVEDQMGRNAME PIC X(48) VALUE SPACES.
    """,
    "CMQTML": """
      * IBM MQ Transaction Manager (MQTML)
       01 MQM-TML.
          05 MQM-TML-STRUCID   PIC X(4)  VALUE 'TML '.
          05 MQM-TML-VERSION   PIC S9(9) COMP VALUE 1.
          05 MQM-TML-OPTIONS   PIC S9(9) COMP VALUE 0.
    """,
}

created = 0
for name, content in stubs.items():
    path = COPYBOOK_DIR / f"{name}.cpy"
    if not path.exists():
        path.write_text(content, encoding="utf-8")
        print(f"Created stub: {name}.cpy")
        created += 1
    else:
        print(f"Already exists: {name}.cpy")

# Fix COPAU00 and COPAU01 - copy from extension cpy folder
ext_cpy = Path("corpus/app/app-authorization-ims-db2-mq/cpy")
for name in ["COPAU00", "COPAU01"]:
    src = ext_cpy / f"{name}.cpy"
    dst = COPYBOOK_DIR / f"{name}.cpy"
    if src.exists() and not dst.exists():
        import shutil
        shutil.copy(src, dst)
        print(f"Copied: {name}.cpy from extension")

print(f"\nTotal stubs created: {created}")
