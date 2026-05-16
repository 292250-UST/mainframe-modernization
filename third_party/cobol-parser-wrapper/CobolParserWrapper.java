import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.CompilationUnit;
import io.proleap.cobol.asg.metamodel.ProgramUnit;
import io.proleap.cobol.asg.metamodel.procedure.ProcedureDivision;
import io.proleap.cobol.asg.metamodel.procedure.Paragraph;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import java.io.File;
import java.util.Arrays;
import java.util.List;

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

            // Paragraphs
            sb.append("  \"paragraphs\": [");
            if (pu != null && pu.getProcedureDivision() != null) {
                ProcedureDivision pd = pu.getProcedureDivision();
                List<Paragraph> paragraphs = pd.getParagraphs();
                for (int i = 0; i < paragraphs.size(); i++) {
                    sb.append("\"" + paragraphs.get(i).getName() + "\"");
                    if (i < paragraphs.size() - 1) sb.append(", ");
                }
            }
            sb.append("]\n");
            sb.append("}");
            System.out.println(sb.toString());
        }
    }
}