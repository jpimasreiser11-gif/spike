# Static check that a script only uses what Windows PowerShell 5.1 understands. Run it with PowerShell 7: its parser
# knows the 7-only syntax and can name it, where 5.1 itself would only say "parse error". Exit 1 lists the problems.
#   pwsh -NoProfile -File tests/fixtures/check_ps51.ps1 -Path scripts/install.ps1
param([Parameter(Mandatory)][string]$Path)
$Path = (Resolve-Path $Path).Path
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
$problems = [System.Collections.Generic.List[string]]::new()
foreach ($e in $errors) { $problems.Add("line $($e.Extent.StartLineNumber): parse error: $($e.Message)") }

# a file without a BOM is read as ANSI by 5.1: anything above ASCII would be misread
if ([System.IO.File]::ReadAllBytes($Path) | Where-Object { $_ -gt 127 } | Select-Object -First 1) {
    $problems.Add('non-ASCII bytes (5.1 reads a script without a BOM as ANSI)')
}

$sevenOnlyNodes = 'TernaryExpressionAst', 'PipelineChainAst', 'NullConditionalMemberExpressionAst', 'NullConditionalIndexExpressionAst'
$sevenOnlyVariables = 'IsWindows', 'IsLinux', 'IsMacOS', 'IsCoreCLR', 'PSStyle', 'PSNativeCommandUseErrorActionPreference'
$sevenOnlyParameters = 'Parallel', 'AsHashtable', 'SkipCertificateCheck', 'SkipHttpErrorCheck', 'AsByteStream', 'NoEmphasis',
    'LeafBase', 'ResponseHeadersVariable', 'StatusCodeVariable', 'AdditionalChildPath'
$encodings51 = 'ascii', 'bigendianunicode', 'default', 'oem', 'unicode', 'utf7', 'utf8', 'utf32', 'string', 'unknown'
$web = 'Invoke-WebRequest', 'Invoke-RestMethod', 'iwr', 'irm'

$nodes = $ast.FindAll({ $true }, $true)
foreach ($node in $nodes) {
    $line = $node.Extent.StartLineNumber
    $type = $node.GetType().Name
    if ($sevenOnlyNodes -contains $type) { $problems.Add("line ${line}: $type is PowerShell 7 syntax: $($node.Extent.Text)") }
    if ($node -is [System.Management.Automation.Language.PipelineAst] -and $node.Background) { $problems.Add("line ${line}: trailing & (background job) is PowerShell 7 syntax") }
    if ($node -is [System.Management.Automation.Language.BinaryExpressionAst] -and $node.Operator -eq 'QuestionQuestion') { $problems.Add("line ${line}: ?? is PowerShell 7 syntax") }
    if ($node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Operator -eq 'QuestionQuestionEquals') { $problems.Add("line ${line}: ??= is PowerShell 7 syntax") }
    if ($node -is [System.Management.Automation.Language.VariableExpressionAst] -and $sevenOnlyVariables -contains $node.VariablePath.UserPath) {
        $problems.Add("line ${line}: `$$($node.VariablePath.UserPath) does not exist in 5.1")
    }
    if ($node -isnot [System.Management.Automation.Language.CommandAst]) { continue }

    $name = $node.GetCommandName()
    $elements = @($node.CommandElements | Select-Object -Skip 1)
    $named = @($elements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] })
    foreach ($p in $named) {
        if ($sevenOnlyParameters -contains $p.ParameterName) { $problems.Add("line ${line}: $name -$($p.ParameterName) does not exist in 5.1") }
        if ($p.ParameterName -eq 'Encoding') {
            $value = $elements[[array]::IndexOf($elements, $p) + 1]
            if ($value -is [System.Management.Automation.Language.StringConstantExpressionAst] -and $encodings51 -notcontains $value.Value.ToLower()) {
                $problems.Add("line ${line}: $name -Encoding $($value.Value) is not accepted by 5.1")
            }
        }
    }
    if ($name -eq 'Join-Path' -and $named.Count -eq 0 -and $elements.Count -gt 2) {
        $problems.Add("line ${line}: Join-Path with more than two arguments needs 6+")
    }
    if ($web -contains $name -and -not ($named | Where-Object { $_.ParameterName -eq 'UseBasicParsing' })) {
        $problems.Add("line ${line}: $name without -UseBasicParsing needs Internet Explorer on 5.1")
    }
}
$requests = $nodes | Where-Object { $_ -is [System.Management.Automation.Language.CommandAst] -and $web -contains $_.GetCommandName() }
if ($requests -and -not ($tokens | Where-Object { $_.Text -match 'Tls12' })) {
    $problems.Add('web requests without [Net.ServicePointManager]::SecurityProtocol set to Tls12 (5.1 defaults to TLS 1.0/1.1)')
}

if ($problems.Count) { $problems | ForEach-Object { "FAIL: $_" }; exit 1 }
"OK: $Path parses, is ASCII and uses nothing newer than Windows PowerShell 5.1 ($($nodes.Count) AST nodes)"
