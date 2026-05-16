import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.CompilationUnit;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import java.io.File;
import java.util.Arrays;

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

        Program program = new CobolParserRunnerImpl()
            .analyzeFile(inputFile, params);

        for (CompilationUnit cu : program.getCompilationUnits()) {
            System.out.println("{\"program\": \"" + cu.getName() + "\", \"status\": \"ok\"}");
        }
    }
}