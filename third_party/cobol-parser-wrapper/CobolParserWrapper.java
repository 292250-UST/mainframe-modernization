import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.CompilationUnit;
import io.proleap.cobol.asg.metamodel.ProgramUnit;
import io.proleap.cobol.asg.metamodel.procedure.ProcedureDivision;
import io.proleap.cobol.asg.metamodel.procedure.Paragraph;
import io.proleap.cobol.asg.metamodel.procedure.Statement;
import io.proleap.cobol.asg.metamodel.procedure.StatementTypeEnum;
import io.proleap.cobol.asg.metamodel.data.DataDivision;
import io.proleap.cobol.asg.metamodel.data.workingstorage.WorkingStorageSection;
import io.proleap.cobol.asg.metamodel.data.datadescription.DataDescriptionEntry;
import io.proleap.cobol.asg.metamodel.data.datadescription.DataDescriptionEntryGroup;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.Token;
import java.io.File;
import java.util.Arrays;
import java.util.List;
import java.util.ArrayList;

public class CobolParserWrapper {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: CobolParserWrapper <file.cbl> <copybooks-dir>");
            System.exit(1);
        }

        File inputFile = new File(args[0]);
        File copybookDir = new File(args[1]);

        CobolParserParams params = new CobolParserParamsImpl();
        params.setCopyBookDirectories(Arrays.asList(copybookDir));
        params.setFormat(CobolSourceFormatEnum.FIXED);

        Program program = new CobolParserRunnerImpl().analyzeFile(inputFile, params);

        for (CompilationUnit cu : program.getCompilationUnits()) {
            ProgramUnit pu = cu.getProgramUnit();
            StringBuilder sb = new StringBuilder();
            sb.append("{\n");
            sb.append("  \"program\": \"" + cu.getName() + "\",\n");
            sb.append("  \"status\": \"ok\",\n");

            // ----------------------------------------------------------------
            // Paragraphs + statements per paragraph
            // ----------------------------------------------------------------
            sb.append("  \"paragraphs\": [");
            List<String> paraList = new ArrayList<>();

            if (pu != null && pu.getProcedureDivision() != null) {
                ProcedureDivision pd = pu.getProcedureDivision();
                List<Paragraph> paragraphs = pd.getParagraphs();

                for (Paragraph para : paragraphs) {
                    StringBuilder ps = new StringBuilder();
                    ps.append("{");
                    ps.append("\"name\": \"" + escape(para.getName()) + "\", ");

                    // Extract statements per paragraph
                    List<Statement> stmts = para.getStatements();
                    ps.append("\"statements\": [");
                    List<String> stmtList = new ArrayList<>();

                    for (Statement stmt : stmts) {
                        StringBuilder ss = new StringBuilder();
                        ss.append("{");

                        // Statement type
                        String stmtType = "UNKNOWN";
                        try {
                            stmtType = stmt.getStatementType().toString();
                        } catch (Exception e) {}
                        ss.append("\"type\": \"" + stmtType + "\", ");

                        // Line number from context
                        int line = 0;
                        try {
                            line = stmt.getCtx().getStart().getLine();
                        } catch (Exception e) {}
                        ss.append("\"line\": " + line + ", ");

                        // Raw text from context
                        String raw = "";
                        try {
                            raw = stmt.getCtx().getText();
                            if (raw.length() > 200) raw = raw.substring(0, 200);
                        } catch (Exception e) {}
                        ss.append("\"raw\": \"" + escape(raw) + "\"");

                        ss.append("}");
                        stmtList.add(ss.toString());
                    }

                    for (int i = 0; i < stmtList.size(); i++) {
                        ps.append(stmtList.get(i));
                        if (i < stmtList.size() - 1) ps.append(", ");
                    }
                    ps.append("]");
                    ps.append("}");
                    paraList.add(ps.toString());
                }
            }

            for (int i = 0; i < paraList.size(); i++) {
                sb.append(paraList.get(i));
                if (i < paraList.size() - 1) sb.append(", ");
            }
            sb.append("],\n");

            // ----------------------------------------------------------------
            // Data items from WORKING-STORAGE SECTION
            // ----------------------------------------------------------------
            sb.append("  \"data_items\": [");
            List<String> dataItems = new ArrayList<>();

            if (pu != null && pu.getDataDivision() != null) {
                DataDivision dd = pu.getDataDivision();
                WorkingStorageSection wss = dd.getWorkingStorageSection();
                if (wss != null) {
                    for (DataDescriptionEntry entry : wss.getDataDescriptionEntries()) {
                        StringBuilder item = new StringBuilder();
                        item.append("{");
                        item.append("\"name\": \"" + escape(entry.getName()) + "\", ");
                        item.append("\"level\": " + entry.getLevelNumber() + ", ");
                        item.append("\"scope\": \"WORKING-STORAGE\"");

                        if (entry instanceof DataDescriptionEntryGroup) {
                            DataDescriptionEntryGroup grp = (DataDescriptionEntryGroup) entry;

                            if (grp.getPictureClause() != null) {
                                String pic = grp.getPictureClause().getPictureString();
                                item.append(", \"pic\": \"" + escape(pic) + "\"");
                            } else {
                                item.append(", \"pic\": null");
                            }

                            if (grp.getUsageClause() != null) {
                                item.append(", \"usage\": \"" + grp.getUsageClause().getUsageClauseType().toString() + "\"");
                            } else {
                                item.append(", \"usage\": \"DISPLAY\"");
                            }
                        } else {
                            item.append(", \"pic\": null, \"usage\": \"DISPLAY\"");
                        }

                        item.append("}");
                        dataItems.add(item.toString());
                    }
                }
            }

            for (int i = 0; i < dataItems.size(); i++) {
                sb.append(dataItems.get(i));
                if (i < dataItems.size() - 1) sb.append(", ");
            }
            sb.append("],\n");

            // ----------------------------------------------------------------
            // Token stream
            // ----------------------------------------------------------------
            sb.append("  \"token_stream\": [");
            CommonTokenStream tokenStream = cu.getTokens();
            List<String> tokenList = new ArrayList<>();

            if (tokenStream != null) {
                tokenStream.fill();
                List<Token> tokens = tokenStream.getTokens();

                for (Token token : tokens) {
                    if (token.getType() == Token.EOF) continue;

                    StringBuilder tok = new StringBuilder();
                    tok.append("{");
                    tok.append("\"type\": " + token.getType() + ", ");
                    tok.append("\"channel\": " + token.getChannel() + ", ");
                    tok.append("\"line\": " + token.getLine() + ", ");
                    tok.append("\"col\": " + token.getCharPositionInLine() + ", ");
                    tok.append("\"text\": \"" + escape(token.getText()) + "\", ");
                    tok.append("\"hidden\": " + (token.getChannel() != 0));
                    tok.append("}");
                    tokenList.add(tok.toString());
                }
            }

            for (int i = 0; i < tokenList.size(); i++) {
                sb.append(tokenList.get(i));
                if (i < tokenList.size() - 1) sb.append(", ");
            }
            sb.append("]\n");
            sb.append("}");
            System.out.println(sb.toString());
        }
    }

    private static String escape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}