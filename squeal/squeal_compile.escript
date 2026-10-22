#!/usr/bin/env escript
%%! -noshell
%% Компиляция Erlang abstract forms squeal (см. architecture.md).
%%
%% usage: squeal_compile.escript JOBS
%%   JOBS — файл с одним Erlang-термом: [{FormsPath, BasePath, Source}, ...]
%%   FormsPath — файл термов (ASCII): одна форма на строку, каждая с точкой
%%   BasePath  — без расширения: MODULE.beam и MODULE.erl лягут рядом
%%   Source    — путь исходника .ee для атрибута -file и debug_info

main([Jobs]) ->
    case file:consult(Jobs) of
        {ok, Jobs_} ->
            compile_jobs(Jobs_);
        {error, Reason} ->
            io:format(standard_error, "read jobs failed: ~p~n", [Reason]),
            halt(1)
    end.

compile_jobs([]) ->
    halt(0);
compile_jobs([{FormsPath, Base, Source} | Rest]) ->
    case file:consult(FormsPath) of
        {ok, Forms} ->
            case compile_one(Forms, Base, Source) of
                ok -> compile_jobs(Rest);
                error -> halt(1)
            end;
        {error, Reason} ->
            io:format(standard_error, "read ~s failed: ~p~n", [FormsPath, Reason]),
            halt(1)
    end.

compile_one(Forms, Base, Source) ->
    Options = [return, report_errors, report_warnings, debug_info, {source, Source}],
    case compile:forms(Forms, Options) of
        {ok, _Mod, Binary} ->
            write(Base, Binary, Forms);
        {ok, _Mod, Binary, _Warnings} ->
            write(Base, Binary, Forms);
        Other ->
            io:format(standard_error, "compile:forms failed for ~s: ~p~n", [Source, Other]),
            error
    end.

write(Base, Binary, Forms) ->
    ok = file:write_file(Base ++ ".beam", Binary),
    Erl = [erl_pp:form(Form) || Form <- Forms],
    ok = file:write_file(Base ++ ".erl", Erl),
    ok.
