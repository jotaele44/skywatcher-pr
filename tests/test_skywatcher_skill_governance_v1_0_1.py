from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
import zlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" / "skills"
DESIGN_PACKAGE_SHA256 = "0a8db5ee463178bc9e0667f967597a743a98e625de992081db132a46e54bf068"
IMPLEMENTATION_BASE_SHA = "7dccd6c9a7e506a33aceae9c3e88466fdff47b35"
CLASS_ORDER = {"PUBLIC": 0, "INTERNAL": 1, "PRIVATE": 2, "RESTRICTED": 3, "SECRET_BEARING": 4, "CREDENTIAL_BEARING": 5}
MIN_GOVERNANCE_OUTPUTS = {"SKILL_EXECUTION_RUN", "INPUT_ACCOUNTING", "VALIDATION_RESULT", "SKILL_RECEIPT"}
ONTOLOGY_CANONICAL_SUBTYPES = {"ILAP", "SOURCE_OVERLAY_TRACK_LINE", "STRUCTURAL_FEATURE_CANDIDATE", "CORRIDOR_FOLLOWING", "LANDING_CANDIDATE", "TAKEOFF_CANDIDATE"}

_FIXTURES = json.loads(zlib.decompress(base64.b85decode("c-rk<Yj@g4wEZhud^Qdb1IBz(gdFPz5S4`U=*pTU^Z+#iaV6o@?dpHO=gf>AVB`2YX`8kuA6hJp=5_Y$bIzVY{NC6lS(Hb2LF4M@-y6Q0yN#>g8?FbJ+&oIQEZc83ZhGIiYN+C3poB@P1i$X$$cu8tn5c8b&9cOc_yfu+*aoTi_$A8M%GTWkz7lPB`#e+Jt*>M|xa-EsCdk)`f8IE2xLY^A&m+%`8863@<u8GkXVB=iF&i7RH&@qlW6CUZ;pps*ZccT_`oQG9k!>z4O=qg*7}u)iTp6=#OSK(qp*agnXO@1gTl!4XM^jz3;mTB>IahPbd~Zw*=L4%<J?u-e&ksAJ+P0|~s$-b5D;zfz_uOr=<)v|)P)0K?%b1F3QKJ+F>jlc|H1b!$LGk1ZOjB9@;MQ)Rf>n5BX@C=+26s{LrI~Ew`-k%_yQhR{vQcoFlrWA~>%0lmyjH?!>qpyFb_Ny*Q#Z@gy_fG(tTPPKVCw~N3$5Y@UhJm9v3audgRW(tqZo|jL*Kk4O`}aSirrn)l>==q9}e^`NHgdsJkdUHowu8QkVUKQc^eA(LFn$|oVj~wDvk1c<^@p<-G#!Iu8x^Gn|xsEY|JL6rcO!=+qGvs*T+%76XuMK^(mBwyQ>76-MVl?S`p1>zcnTkroY#<1)7jqi`mGS%@+<+HO*Yi90b#?Ix)toxUbubi8B(9S-Pehb7yp|8WVvkupIQzVmHvFd40{^-2lv(I-gGrO?^Glp&QX=7YCbQo6EHX|Hqz=b=!C|6Qi4%P}SVD4aWpX!{Cft-a0%TM`7UIdvS35przj$wmxQaoi6~UE}R?FGCmd$ZlVmQoFyr&ryQDx|4C~XbNyQYHVoZ33(gu~DfZ}!A1BH-$rb*v;(CA;088w0M4c%d!Pz?6ohcHrXNs33Dct21!C&q^lOKUHlAYuQ09P8s!5x|h;RS63Xdg3;RuSIKl6?xR<_oWD1%)?mw9S-V8e~Cw$Js=d$zBOc;eRlI;AeLQ7ta-~z#sN^wTG)fTXCFx$&_T9Cvmd6SME9hNN9hTChKS!<$+%V3qV4*ZKh3BV>+6sVxq-g06}Ad%rReBU^#tczMJWmePhfSP><vq%>;NDGj5WRrY>yp$(-vJ|D<wAnNy&habdSKSVgcx?^zna>hi@p<M3;?S_3Sw-{#RKs96iGWY`F|F{{A}%8I25i#j`^F1#n^%T2vCP(RDoZl~AB73%lGVXNQ2=mp(y=w4p*gWlyu*Y9@Qt-)Y<>35c`u;+HY;lOpf%YNVwFIwSccQ6RTu(R~5s--EaszYzk3okqV(hryIi%!sA_S;^oKj>dT18%<;`h(UGs=M%8-DRgc^jcwe7`BJK*5%M!wtBUyQ&`+$ZRZi^P<yUxd^Tr-_4RR88jw~@l%~$i8LZ8T@eyW=8;#AuI~eb);x&Rh!E6TwH-0t3WjOHrFdKuxMZe><Tb*9-((A!|^}UPMrGM%A?P1vI58Lf_D{zN{?&W3YqJ0tg!Ll>#4VG2ihm_fB`~ho3co#vs47(<KaD<ujUov<QYVy{wYT${-ONrZ}@E>P2$6qorp8_P7rv6@?&L=uRu>CS$0I@;@OP9HM<7&H)W1#2M-QsdvBFn7z8+Tjsk}#Gar5uVC(Fr&%pempcNp6|!Zo)P}3e6N`<|Ug=lvjUp56YHMleaFff)C=35W)WihFd)@qnCii369ZC^C)z=_ZJ-iX8a73==%5NBZut+%Wc7f^Ev<DJ+xEa0l(_4WxYUcpYt@R9s^KsfCdYuFRt#hs?*pi^OEfr+&#>lB*4SlX~5&TB)vbpUKSRkK>BsFs+}y@`YiZ0N1qwXtAB915%vX7c?5&ZgMmWK$g5Yf{SLxGAm$?6XjC()@DVH3Ony3R<StBEj)MU^0Jr1({@i%A+2*ehi3&zKjZYQq`55pbbTaVv+)b5GJpuX0N}hy0__ke+E^z?hh%ylr!=r#qaKc#*6B|O!(mlKqQEIJVcJ5_&7?tcXEaoO`gZt;jpz;KHd%Kd0O4FR9*(^Mu{;P`-10O$nCK-W>MGFNk&~z|sUKC?z3uFGm5y6`jp`!SB+Io4Cqn+EWv&Mc4OEZb@@cC9X<Hub;G06{#ou1(`zSt!&MFqjYR6Ic*&AT>hG3@bkh=~V+2i0rp_<7a8B*IP5RJan6*BYHxr{8Q{Hd|e%)4A%luUf5-ywo;~R{K<jR)w!<edE7I!EBGW-jc23?6XbcAI=KI8|w3><=FrhNeCzE=OisMTPbNnq%D#=ctm$HTRG=(666WHT%ub9=0_cRin@RoIFjmfV(Z%TrbOW5iKGS?e1(e{(rH)=-sfEsZDm)ro3}@O3Ee1$@$uWjH6E<LJ2#H}!XswrPk5@+maWLHJL(&~DVxss8Aq<fCSQX`-4N}ZY`JD8mZSfwx7>N8<<5zgKk>`y6BzA%Jk{x<GZl%0LBC4$SmqP~eccvMFQ^V*P*q#pQCADP^Ns(?#dcJ0`y2mNPNZ~YMcu;c!2W0?mbqb2c@)S210KLY;D-4t_s<#FL<l*`+RfGhdU<}0+d(PTguGZXwjyGMPhVM-PlLM_0+)t7frnawlisK%@^I#2%OY@raq90KOT{dLnXhf#y2b43N{US8t!_=!4-8AZWfNnj<G_mG2EzniMG+{-fF9L|*uBSq*89xjXbU`sor?LxrEBByE)ZQ>OU|D{Wv8Hdu%S%4OI-;m_2^d3wS_w%x-jirG*jqm(1h3zx(0D0JhBG<O~OzVl;XxQyF&EH+0UBTQ>9$E%3YN0A=cx=RAimd@<<RobS=YsIN=bXDyU7QkkkuxL=ZbioX@twmnv*~7-q_<;Zw3iNkBN2he79oU%|O9lETM<*m*P$Oyf+>RR+cgw%Iz#o6#0>P#$O37z~1VltC~JuEHt?gu37CL=RykvqV`1N$Jp(WpJNtYhx22NYc%DJpz_SIRW|N?n&}{L3r~7?uy_BJiLgx3fK#k_Z6ax71J((epcK(^z3D3$^+<6b-#o)eyYP!UU+s;5=W2;y5+>HHPI9(3G4$&Ng#F3<`Qc2WzeFy(AXK*zPN-HD`45ByNqH8_Avzc^t8qXSt=T^F0lb(nOF?Cs4&9G*TI2~n+3U&CyJ}^d|37*NKrZCeFJDnZ5f^lvJ7b%C9=<9oP0S*77i(hYX$Y#t74w##8I+H>5#hL`0p#R*)yW6<7fdcmWt&ytlqCgo-n6@5&$yb*%8>d6gEo{Q=0Zn5r*aBWhrGUUhGC2<%^ps8^}0t;;Sf)q34Wq5&hLy$8&PW6*_)CFEwnJ>0Wj~G$`uf0zcKp37gj&*(MKw`>=_F9GoNJq`)NZp7gk=y#k%UdWe_k1TiZS%TkKh;BHk*yD@I{F=F!tl=ZFIPT4o<hB8*{aviBtGE54g$QoRER*#gRMdMWNqHOkAu7K&i7=We(VJMO&1$rK2BL(sjD3~{S3@Ct>DY9<Gs}ybdh>PIk<CRqkJ{2ysishtBEhoH`K_Ps(#a)UM7RUf~fR1ujDw$l=T|wh`;!j}YL9y@au3#bH##MbXj=PNd-LKJRzmdWPSI46e6&t}fmTo(iAr<7JtR&W_3&V2qA;4LsKnm5|`-1Zyu?nudN)3V9=5lv~i$6-WO;g7Y`VA3!j}%{Q&XkH1I1reGytxeA6n9O4mG&ZC7B`-rmv2dmD<B-zasmg(rB1`(aYcs*uh17Sb;G;~V+jGN*ry=;ilXzxlRTV3yaV6*k+87HkkB2#`a!R?4A$;ll%(AFKP?PPXE%$fiW`rbVav_81Od=^r|WMgA8>!LzAuSG_4jePgHsC;%3DA>0EMj91KjiZE!kqV>Ly5GRIldyAk7nIMP5?RjSgn)RDN_==zA{0WE(=Ad3~OW-BHIBJ1$~BK(H$I`d}|hP6ft*jB{j(&!auc(ny@qpr;T`r7{oYX~qt^2_Zo(38{;SiVJDO7Nw2c%{~_to5@fB{k;qZl*%`Ls$^OS;qzq2xwz_+khCzWgREwAEMU1Y*pF{EzC`^jN&JbNNQBp45#Gy+WND~{=SVyY#JmKeVVE@;yVs`7<$mgvD#sJeN6!z4Mj_VOW)Y8{@7ad$gB&yB={>Ip((wsgKP-0&+HxcLa8rH`bPmZrI6+A9U#pHWWvb0&+OOXlW8BsiyT!%!BRAsQGH)L@pBTtrvD=EkL~<;atPE6?2q5kId<RV&@<;&W=rz)SZ+mgLiaO5!lD*p>a(fjC_S8Od&A06WueSGm%C{YrIvEf1*bm)`*y`s2f8(m%X+7n-PAE3WAtI8ja!ea};r_9xQK=o@sz(}t5Jh6tf91K*ab*pud6EjEL&+?QctBC)=*8gz46)hN9P4aq*i+TfZjPkw2A-NZ&dz~Iguu-n6{t7B#4c{EHYR1yG3zRbLs{-~5i7w8jxj#Q9+$;RUPRm%F)Y7>_^-k%o;iCw@_t<G=t;3-heTT25<aE%mCBGXx=6E802KNGhI%4qP{;qX7(*N`&l>S?VthJ1?lumD(FYp@6;g|tfAU1YQK18zekw|{ZLo45o(}wB4hhh4fdAHUfH3+M0}oU$Bru_ye9Ih`A4lw~3Y;7n+Z8)JN%B2T3;eK$WD1<nvY=&gYFQj&hVfB+k45oM5cvM{g55KaQcZF}pk;*z^z*GEA1T6rIlxM;`%w^9>*Z5C^d}3)w9om(J}2#5($3{Sb?5RKTvVW>@O2Nj^~2a*y>Qc$=;-e{b|E(nh`Wfp{v+IVuqF`xFFmM1U;U-8{?b=}>8ro=)nEGRFMaj*vAyX>jw(FMTT2TUsfMf#&vSk2w|2>ik`pB-N=}rVC^=Djf5!K6&=1%2xB6+yttl+{Cx->(kI5gCKPG?t_xR(7Ny$t6F&<-pzW{jNiQ}#1KEQwZ)j;isuLi1p`GnpSMrR;@tTT|+cL<*Q?j3sH%a8oNm)e<xlH-1^cF*Z}1-;dR&R5X+iWi@+0CUlM3F*Cr^j<=GFX8{^y@W?bqPLa&^WIi+pgxpRfV_mBOnfQ1#xBssd<_v*<Q0NLx{vYc<K0iDT848o)g41Se!nnD3Xi>Qm?Q;~6rLj~n9dD<bqt9KBqorUKw<)k2_z<vm_T9zi3ubokeEPX!VfPdl+2E6HjcKRkCX&?<jMJfr>gOH1>TZ?@K*^4PrX`?<O4d9Kq3N(2qYqqh(IC&i3lVjkcdDc0*MGDB9Msi_lXF?tWU}a;#=1wB+y9&k`hQtASr>Q1d<X+N+2nLqy&-@NJ{udDM5N$QVvKtAm!j6pd8>YQsSFP%2z2Ai}?`=!O^X$Az$Z#(FJJ;q#=-oKpFyR2&5s9hCmtuX$YhtkcL1S0v$&nQ9(Y6ujGqk5*7YiqC#o*Qcc*nyB+lPNKnw!nWj(hg`S0?FjePsWA=tb1rilVR3K4-L<JHRNK_zEfkXuo6-ZPdQGrB-e~75irjrUJDtup2q3kLX$SS~gq$w<B#!m~Knbugh^fBYmW3~?0W|~gA0_h5*E0C^0x&rA6q$`lFK)M3y3ZyHLu0XoNzvZyP5@O5Gq$-fA@Z6&cC5z&UmFN))!|`DS6W5JXY6|!poQCb_GwlP(3M4C#tU$5?$qIj-tWf^W2MG!!D3G8)f&vK&Bq)%eK!O6jQh_9eA4^iG(0Sq~9kd%=dpkFcnM1$nKoSB;2qYnpgz$r%Ob~Jdi3ubokeEPX0*MJECXkpwVgiW?BqscAVuFCy({h41nm~dA2?``Akf1<<0)5qi!~_x(NK7Cxfy4w76G%)TG2!1NCd?PFCx%8s!gGX#vW;@0j#LC_Z^3^ba%Qrz`EK^cQpfbd1X2-5MIaS{R0L8Hen1tW_)ZAv2c#d6en9#G=?A1AkbXe=0Ubv8b2NlvG1pk;k>d!(Z#e+>n2VWX%-%dakdW=UFNT;ZO}-o<ro6=)K{Ot+etDmVhy|>|I9jdqCPbIb+OlZ6kd58{7NjE#Qj0>6My{KMN3DvW--n6Xz@ka-AKq^q$Q(Gk^NHawbEY%LWX_GH>riA3;Vsx5dzxb`m?Onv2!{v(!0Fbl&Te(<wdxpC)LM)gn@?0tXO{lXG8~<grkn8=4AGY}rPlE?4k9m2vaIPR8%X_>H->!>VJ?F>0RTaeX=5vAoV3MrGO`4#?t~W*qKQau8CcoPiUb<aqgvXH`g(#dyO_?Qs@KK@6(V(Fs5bO{#xxcFYiR1Esso^T7i{qtKp4c(DW4}@!(aF?Z}F9!Rml`F1nE^3aG=LCY;1AN5IPfP>vPpo9i16S#Z!IeKsU@;RY{Ftg#BtjC`?$DK6D1H=c{Ljpgfk&7MiBpwrMerc&7ifP;sITAipf~dUQ8#46!`0Z5h_#R3Vz3_Q>gsobJfEU@*sHU7M)*9@Ez!m~AdB4dGEdd>3UAPgU*(wQ)J@wl%tKk8V4o+wSQ0L>)|>joDOpZcMa>?3kFt*T!rNwBLGJpydNa7P*fxn=hP3mC)6aXt-;>o9Pz2fsUBh*8q;676x|l-HkpgIw^{bjq7XOvKvn)Vins$-8>bmDTMZZncwdqV+Z~fDSC4S7)?1y6*+t*c467@HR310)JV-J=fK~|Hc#SYb+6oY05oL?#lTx|e3uhk?|4-#6U}4N0?UwD<^tgSMmNC#)(3VC6OO-lQx?Zx<YlF&wci?(344P}XNJF)!|cUt=ffOfP;`qG56VW$3JagbIBa2*Xc-iz8s&TgWF6Ih%WTb@!_q{&{^-zb6Eyz>Xd1I?OND4?p*af+eG!a|zcKl{;j*x=<rvqHOa5!|*&%%X3HY2_=6hp`!N*irZGb3-0^bjuhn2nnm|SEN(x#MUkEE1Jx>Ci(Knar+<_V+!D1VT5D^mQ&k6)sEtzgdQ3)NZV5da`em!z(VlglI3oa0WUM`Dm!<rS`;a6zM^6?%1w6GpY!x;kZ;T3=-PRdq&%SV=Q@Aa{l1K3Fj_x0Qh^pB7cF7UgxBEtbU#B#H6|x1`SZJe@<4-4k+$P&ulgyHq^RPRku4!1e<m6u{1rd3YZ8lC-#d<Ov<a4?=ez=d4oRAWw_=J}n?t1+>m4A2@SOOo-J>3){74r6z~`G6UY5LTOYH%f&9OSS>I8y{;|Lg!moy5vQzL$~U@&2zacD`?|fDI3w|x%nnD_sxc9$0?YCBR4^J48C+NAkX>n*3ZS@!as$$zTWvXU_OOjNGch{Iq%3`I+J<8Sq+xKzZILO&Q5bmlUK|`hXz90x4U2iM^98_Asx&R*WAWe%XmiURUGrm+>+{D;9XfV7rp^?O;cOl4YTC4y0Ea|dUeQ^lN^^}m*-2&qc;P<e9UADoM%!i@ts=ZD(jMGB;6x2R1oFj9*-5Da`9zk<UI|i>Nu29_Ms4iXxuO*a#Qv`Ka21FP-DviZ-78t51{aklM+}JGn2si@m}>DCfKX(V^MwVr(?^{D?HgkbX>q|enh5|gX51(vO<maH6Y#FZKdBs4<`jr$Tv+aii=`TZ0Bp8e10gy-k$cvFRqBX5PB<j5TH>5~YupL1wk!Q!IBfO%7rmex4&BR(e$czT==$AmyEParFa6H4753b&HypTbci9j8;YBOF><$J&7<QI^EuR*qsHzUVK`*@Q_)9-rwl6wCf7x$)t^S~Y0S&nQUg!^6L#Xb;Z*`ZQ?$B$6-C@`s_F9)iZ`tZSD^;Hf-akm!gSeQeGVM1$qA%pp#vJ^E@&3`o`~<fh6x{gL2$$i&@55{i1{eK~*KT!sy-TkL^VRn*T9^K%>$ittr$21B+pWMI4!W0@os0HG;0Mdjus2wKd%hnftcdM^1U7i=;DO5Z#<0<Q8s_8qK7|7m4*Vy=0rJn}pUFRyfBq}|Ghg}OoF5X>k(;iG0N~{yN3l!AgeUEyy5)ZBV{tm;N@rZ@j4PdSr8BN{#+AM)ODA3Fq${0trIW67(v?oS(n(i3>H4oY>H5e20WKPh69")).decode("utf-8"))
POSITIVE_CASES = _FIXTURES["positive"]
SCHEMA_NEGATIVE_CASES = _FIXTURES["schema_negative"]
SEMANTIC_NEGATIVE_CASES = _FIXTURES["semantic_negative"]
VALID_EXECUTION_BUNDLE = _FIXTURES["valid_bundle"]

class SemanticValidationError(ValueError):
    pass

def require(condition: bool, rule: str, detail: str) -> None:
    if not condition:
        raise SemanticValidationError(f"{rule}: {detail}")

def read_csv(path: str) -> list[dict[str, str]]:
    with (ROOT / path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def object_pairs(value: str) -> set[str]:
    return {item.strip() for item in value.split(";") if item.strip()}

def validate_accounting(accounting: dict) -> None:
    expected = sum(accounting[key] for key in ["accepted", "rejected", "duplicate", "review", "unresolved"])
    require(accounting["total"] == expected, "INPUT_ACCOUNTING_ARITHMETIC", f"total={accounting['total']} expected={expected}")

def validate_security(policy: dict) -> None:
    require(policy.get("no_downgrade") is True, "SECURITY_NO_DOWNGRADE", "no_downgrade must be true")
    require(CLASS_ORDER[policy["maximum_output_classification"]] >= CLASS_ORDER[policy["maximum_input_classification"]], "SECURITY_NO_DOWNGRADE", "output classification lower than input")

def validate_authority(authority: dict, run: dict) -> None:
    require(authority.get("non_transitive") is True, "AUTHORITY_NON_TRANSITIVE", "non_transitive must be true")
    require(authority["run_id"] == run["run_id"], "AUTHORITY_RUN_LINK", "run mismatch")
    require(authority["canonical_skill_id"] == run["canonical_skill_id"], "AUTHORITY_SKILL_LINK", "skill mismatch")
    require(authority["authority_id"] == run["authority_id"], "AUTHORITY_ID_LINK", "authority mismatch")

def validate_execution_bundle(bundle: dict) -> None:
    run, authority, accounting, receipt = bundle["run"], bundle["authority"], bundle["accounting"], bundle["receipt"]
    validate_accounting(accounting); validate_authority(authority, run); validate_security(bundle["security_policy"])
    stages = run["stages"]
    ids=[s["stage_id"] for s in stages]; seq=[s["sequence"] for s in stages]
    require(len(ids)==len(set(ids)), "UNIQUE_ORDERED_STAGE_SEQUENCE", "duplicate stage_id")
    require(len(seq)==len(set(seq)), "UNIQUE_ORDERED_STAGE_SEQUENCE", "duplicate sequence")
    require(seq==list(range(1,len(stages)+1)), "UNIQUE_ORDERED_STAGE_SEQUENCE", "non-contiguous sequence")
    by_stage={s["stage_id"]:s for s in stages}
    cps=bundle.get("checkpoints",[])
    require(len({c["checkpoint_id"] for c in cps})==len(cps), "CHECKPOINT_ID_UNIQUENESS", "duplicate checkpoint")
    for cp in cps:
        require(cp["run_id"]==run["run_id"], "CHECKPOINT_RUN_LINK", "checkpoint run mismatch")
        require(cp["stage_id"] in by_stage, "CHECKPOINT_STAGE_LINK", "checkpoint stage absent")
        require(cp["sequence"]==by_stage[cp["stage_id"]]["sequence"], "CHECKPOINT_SEQUENCE_LINK", "checkpoint sequence mismatch")
        require(by_stage[cp["stage_id"]].get("checkpoint_id")==cp["checkpoint_id"], "CHECKPOINT_STAGE_LINK", "stage does not reference checkpoint")
    terminal=run["status"] in {"completed","partial","blocked","failed","cancelled"}
    if terminal:
        require(run.get("receipt_id")==receipt["receipt_id"], "TERMINAL_RECEIPT_LINK", "terminal run receipt mismatch")
        require(receipt["run_id"]==run["run_id"], "TERMINAL_RECEIPT_LINK", "receipt run mismatch")
        require(receipt["input_accounting_id"]==accounting["input_accounting_id"], "RECEIPT_ACCOUNTING_LINK", "accounting mismatch")
    if run["status"]=="cancelled":
        require(receipt["status"]=="blocked", "CANCELLED_RECEIPT_MAPPING", "cancelled must map to blocked")
    if run["status"]=="completed":
        require(all(s["status"]=="completed" for s in stages), "COMPLETED_STAGE_CONSISTENCY", "completed run has non-completed stage")
    require(receipt["mission_or_intent_inference_performed"] is False, "NO_MISSION_OR_INTENT", "receipt authorizes inference")

def dispatch_semantic(rule: str, payload: dict) -> None:
    bundle_rules={"INPUT_ACCOUNTING_ARITHMETIC","AUTHORITY_RUN_LINK","AUTHORITY_SKILL_LINK","TERMINAL_RECEIPT_LINK","CANCELLED_RECEIPT_MAPPING","UNIQUE_ORDERED_STAGE_SEQUENCE","COMPLETED_STAGE_CONSISTENCY","CHECKPOINT_RUN_LINK","CHECKPOINT_STAGE_LINK","SECURITY_NO_DOWNGRADE","RECEIPT_ACCOUNTING_LINK"}
    if rule in bundle_rules:
        validate_execution_bundle(payload); return
    if rule=="SUCCESSOR_COUNT_EQUALITY":
        row=payload["successor_row"]; ids=[x for x in row["canonical_successor_ids"].split(";") if x]
        require(int(row["canonical_successor_count"])==len(ids),rule,row["source_skill_id"]); return
    if rule=="REGISTRY_IO_EQUALITY":
        reg=payload["registry_record"]; binds=payload["bindings"]
        actual_in={f"{r['ontology_object_type']}:{r['object_subtype']}" for r in binds if r["direction"]=="INPUT"}
        actual_out={f"{r['ontology_object_type']}:{r['object_subtype']}" for r in binds if r["direction"]=="OUTPUT"}
        require(actual_in==object_pairs(reg["analytical_input_objects"]),rule,"fixture inputs")
        require(actual_out==object_pairs(reg["analytical_output_objects"]),rule,"fixture outputs"); return
    if rule=="GOVERNANCE_OUTPUTS_REQUIRED":
        outputs=object_pairs(payload["registry_record"]["governance_outputs"])
        require(MIN_GOVERNANCE_OUTPUTS <= outputs, rule, "missing governance output"); return
    raise AssertionError(f"unknown rule {rule}")

def schemas() -> dict[str, dict]:
    result={}
    for path in sorted(SCHEMA_ROOT.glob("*.json")):
        schema=json.loads(path.read_text(encoding="utf-8")); Draft202012Validator.check_schema(schema)
        assert schema.get("x-skywatcher-governance-version")=="1.0.1"
        result[path.name]=schema
    return result

def test_registry_and_binding_contracts() -> None:
    source=read_csv("docs/architecture/SKYWATCHER_SOURCE_SKILL_INVENTORY_v1_0_1.csv")
    registry=read_csv("configs/skills/SKYWATCHER_SKILL_REGISTRY_v1_0_1.csv")
    successors=read_csv("docs/architecture/SKYWATCHER_SKILL_SUCCESSOR_MAP_v1_0_1.csv")
    terms=read_csv("docs/architecture/SKYWATCHER_SKILL_TERM_MATRIX_v1_0_1.csv")
    bindings=read_csv("configs/skills/SKYWATCHER_SKILL_OBJECT_IO_MAP_v1_0_1.csv")
    assert len(source)==16 and len({r["source_skill_id"] for r in source})==16
    assert len(registry)==18 and len({r["canonical_skill_id"] for r in registry})==18
    assert len(successors)==16 and len({r["source_skill_id"] for r in successors})==16
    assert len(terms)==43 and len({r["term_id"] for r in terms})==43
    assert len(bindings)==74 and len({r["binding_id"] for r in bindings})==74
    assert any(r["canonical_skill_id"]=="repo-native-visual-calibration-orchestrator" for r in registry)
    assert not any(r["canonical_skill_id"]=="skywatcher-visual-calibration-orchestrator" for r in registry)
    assert all(r["mission_or_intent_inference_authorized"]=="false" for r in registry)
    assert all(r["implementation_state"]=="DESIGN_ONLY_NO_REPOSITORY_ACTIVATION" for r in registry)
    assert all(r["runtime_activation"]!="ENABLED_BOUNDED" for r in registry)
    for row in successors:
        ids=[x for x in row["canonical_successor_ids"].split(";") if x]
        assert int(row["canonical_successor_count"])==len(ids)
    by_skill={r["canonical_skill_id"]:r for r in registry}
    for skill_id, reg in by_skill.items():
        rows=[r for r in bindings if r["canonical_skill_id"]==skill_id]
        actual_in={f"{r['ontology_object_type']}:{r['object_subtype']}" for r in rows if r["direction"]=="INPUT"}
        actual_out={f"{r['ontology_object_type']}:{r['object_subtype']}" for r in rows if r["direction"]=="OUTPUT"}
        assert actual_in==object_pairs(reg["analytical_input_objects"])
        assert actual_out==object_pairs(reg["analytical_output_objects"])
        assert MIN_GOVERNANCE_OUTPUTS <= object_pairs(reg["governance_outputs"])
    for row in bindings:
        assert row["object_term_status"] in {"ONTOLOGY_CANONICAL","SKILL_GOVERNANCE_SUBTYPE"}
        if row["object_term_status"]=="ONTOLOGY_CANONICAL":
            assert row["object_subtype"] in ONTOLOGY_CANONICAL_SUBTYPES

def test_ballot_has_34_decisions() -> None:
    text=(ROOT/"docs/architecture/SKYWATCHER_SKILL_GOVERNANCE_BALLOT_v1_0_1.md").read_text(encoding="utf-8")
    ids=set(re.findall(r"\bB(?:0[1-9]|[12][0-9]|3[0-4])\b",text))
    assert len(ids)==34

def test_all_13_schemas_and_positive_cases() -> None:
    loaded=schemas(); assert len(loaded)==13; assert len(POSITIVE_CASES)==13
    for case in POSITIVE_CASES:
        Draft202012Validator(loaded[case["schema"]],format_checker=FormatChecker()).validate(case["data"])

def test_all_9_schema_negative_cases_are_rejected() -> None:
    loaded=schemas(); assert len(SCHEMA_NEGATIVE_CASES)==9
    for case in SCHEMA_NEGATIVE_CASES:
        errors=list(Draft202012Validator(loaded[case["schema"]],format_checker=FormatChecker()).iter_errors(case["data"]))
        assert errors, case["fixture"]

def test_valid_semantic_bundle() -> None:
    validate_execution_bundle(VALID_EXECUTION_BUNDLE)

def test_all_14_semantic_negative_cases_are_rejected() -> None:
    assert len(SEMANTIC_NEGATIVE_CASES)==14
    for case in SEMANTIC_NEGATIVE_CASES:
        with pytest.raises(SemanticValidationError):
            dispatch_semantic(case["rule"],case["data"])

def test_freeze_manifest_hashes_and_authorization_boundaries() -> None:
    path=ROOT/"docs/architecture/SKYWATCHER_SKILL_GOVERNANCE_FREEZE_MANIFEST_v1_0_1.json"
    manifest=json.loads(path.read_text(encoding="utf-8"))
    assert manifest["authorized_design_package_sha256"]==DESIGN_PACKAGE_SHA256
    assert manifest["implementation_base_sha"]==IMPLEMENTATION_BASE_SHA
    assert manifest["sg0_authorization"]=="AUTHORIZED_ADDITIVE_GOVERNANCE_ONLY_DRAFT_PR"
    assert manifest["sg1_through_sg4"]=="BLOCKED_SEPARATE_APPROVAL_REQUIRED"
    assert manifest["runtime_activation_authorized"] is False
    assert manifest["schema_activation_authorized"] is False
    assert manifest["threshold_activation_authorized"] is False
    assert manifest["mission_or_intent_inference_authorized"] is False
    assert manifest["merge_authorized"] is False
    assert manifest["auto_merge_authorized"] is False
    artifacts=manifest["repository_artifacts"]
    assert len(artifacts)==21
    for item in artifacts:
        target=ROOT/item["repository_path"]
        assert target.is_file()
        assert target.stat().st_size==item["size_bytes"]
        assert sha256(target)==item["sha256"]
    canonical=dict(manifest); expected=canonical.pop("manifest_payload_sha256")
    payload=json.dumps(canonical,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    assert hashlib.sha256(payload).hexdigest()==expected
