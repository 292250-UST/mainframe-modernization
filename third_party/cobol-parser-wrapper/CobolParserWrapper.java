import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.CompilationUnit;
import io.proleap.cobol.asg.metamodel.ProgramUnit;
import io.proleap.cobol.asg.metamodel.procedure.ProcedureDivision;
import io.proleap.cobol.asg.metamodel.procedure.Paragraph;
import io.proleap.cobol.asg.metamodel.data.DataDivision;
import io.proleap.cobol.asg.metamodel.data.workingstorage.WorkingStorageSection;
import io.proleap.cobol.asg.metamodel.data.datadescription.DataDescriptionEntry;
import io.proleap.cobol.asg.metamodel.data.datadescription.DataDescriptionEntryGroup;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
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
            // Paragraphs
            // ----------------------------------------------------------------
            sb.append("  \"paragraphs\": [");
            if (pu != null && pu.getProcedureDivision() != null) {
                ProcedureDivision pd = pu.getProcedureDivision();
                List<Paragraph> paragraphs = pd.getParagraphs();
                for (int i = 0; i < paragraphs.size(); i++) {
                    sb.append("\"" + escape(paragraphs.get(i).getName()) + "\"");
                    if (i < paragraphs.size() - 1) sb.append(", ");
                }
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

                            // PIC clause — getPictureClause() singular
                            if (grp.getPictureClause() != null) {
                                String pic = grp.getPictureClause().getPictureString();
                                item.append(", \"pic\": \"" + escape(pic) + "\"");
                            } else {
                                item.append(", \"pic\": null");
                            }

                            // USAGE clause — getUsageClauseType()
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
            sb.append("]\n");
            sb.append("}");
            System.out.println(sb.toString());
        }
    }

    private static String escape(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}