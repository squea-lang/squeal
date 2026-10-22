#!/usr/bin/env escript
%%! -noshell
%% Компиляция Erlang abstract forms squeal (см. architecture.md).
%%
%% usage: squeal_compile.escript FORMS OUTFILE_BASE MODULE SOURCE
%%   FORMS        файл термов (ASCII): одна форма на строку, каждая с точкой
%%                (не-ASCII символы строк экранируются как \x{HEX})
%%   OUTFILE_BASE без расширения: MODULE.beam и MODULE.erl лежат рядом
%%   SOURCE       путь исходника .ee для атрибута -file и debug_info

main([Forms, Base, _Module, Source]) ->
    {ok, Forms_} = file:consult(Forms),
    Options = [return, report_errors, report_warnings, debug_info, {source, Source}],
    case compile:forms(Forms_, Options) of
        {ok, _Mod, Binary} ->
            ok = file:write_file(Base ++ ".beam", Binary);
        {ok, _Mod, Binary, _Warnings} ->
            ok = file:write_file(Base ++ ".beam", Binary);
        Other ->
            io:format(standard_error, "compile:forms failed: ~p~n", [Other]),
            halt(1)
    end,
    Erl = [erl_pp:form(Form) || Form <- Forms_],
    ok = file:write_file(Base ++ ".erl", Erl),
    halt(0).
