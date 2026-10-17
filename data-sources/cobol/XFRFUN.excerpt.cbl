       PROCESS CICS,NODYNAM,NSYMBOL(NATIONAL),TRUNC(STD)
       CBL CICS('SP,EDF')
       CBL SQL
      ******************************************************************
      *                                                                *
      *  Copyright IBM Corp. 2023                                      *
      *                                                                *
      ******************************************************************
      * Get the ACCOUNT DB2 copybook
           EXEC SQL
             INCLUDE ACCDB2
           END-EXEC.

      * ACCOUNT Host variables for DB2
       01 HOST-ACCOUNT-ROW.
          03 HV-ACCOUNT-EYECATCHER      PIC X(4).
          03 HV-ACCOUNT-CUST-NO         PIC X(10).
          03 HV-ACCOUNT-KEY.
             05 HV-ACCOUNT-SORTCODE     PIC X(6).
             05 HV-ACCOUNT-ACC-NO       PIC X(8).
          03 HV-ACCOUNT-ACC-TYPE        PIC X(8).
          03 HV-ACCOUNT-INT-RATE        PIC S9(4)V99 COMP-3.
          03 HV-ACCOUNT-OPENED          PIC X(10).
          03 HV-ACCOUNT-OVERDRAFT-LIM   PIC S9(9) COMP.
          03 HV-ACCOUNT-LAST-STMT       PIC X(10).
          03 HV-ACCOUNT-NEXT-STMT       PIC X(10).
          03 HV-ACCOUNT-AVAIL-BAL       PIC S9(10)V99 COMP-3.
          03 HV-ACCOUNT-ACTUAL-BAL      PIC S9(10)V99 COMP-3.

      * PROCTRAN DB2 copybook
          EXEC SQL
             INCLUDE PROCDB2
          END-EXEC.

      * PROCTRAN host variables for DB2
       01 HOST-PROCTRAN-ROW.
          03 HV-PROCTRAN-EYECATCHER     PIC X(4).
          03 HV-PROCTRAN-SORT-CODE      PIC X(6).
          03 HV-PROCTRAN-ACC-NUMBER     PIC X(8).
          03 HV-PROCTRAN-DATE           PIC X(10).
          03 HV-PROCTRAN-TIME           PIC X(6).
          03 HV-PROCTRAN-REF            PIC X(12).
          03 HV-PROCTRAN-TYPE           PIC X(3).
          03 HV-PROCTRAN-DESC           PIC X(40).
          03 HV-PROCTRAN-AMOUNT         PIC S9(10)V99 COMP-3.

      *
              PERFORM CHECK-FOR-STORM-DRAIN-DB2

              GO TO UADF999

           END-IF.

      *
      *    If the SQLCODE is OK then update the row on ACCOUNT for
      *    the FROM account.
      *
           COMPUTE HV-ACCOUNT-AVAIL-BAL =
           HV-ACCOUNT-AVAIL-BAL - COMM-AMT.

           COMPUTE HV-ACCOUNT-ACTUAL-BAL =
           HV-ACCOUNT-ACTUAL-BAL - COMM-AMT.

           EXEC SQL
              UPDATE ACCOUNT
              SET ACCOUNT_EYECATCHER        = :HV-ACCOUNT-EYECATCHER,
              ACCOUNT_CUSTOMER_NUMBER   = :HV-ACCOUNT-CUST-NO,
